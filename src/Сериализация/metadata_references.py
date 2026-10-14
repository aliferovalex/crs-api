"""Resolve design-time enum values from validated current native metadata."""
import base64
import re
import uuid
from xml.etree import ElementTree as E
import metadata_serializer as s
import metadata_identifiers as ids
import serialization_context as contexts
import typed_value_xml as values
import appearance_xml

XR='http://v8.1c.ru/8.3/xcf/readable'


def enum_name(reference):
    parts=reference.split('.')
    if len(parts)!=4 or parts[0]!='Enum' or parts[2]!='EnumValue' or any(not re.fullmatch(r'[^\W\d]\w{0,79}',p,re.UNICODE) for p in (parts[1],parts[3])):raise ValueError('Unsupported design-time reference: '+reference)
    return parts[1]


def required(xml):
    if xml is None:return set()
    if not isinstance(xml,str) or len(xml.encode('utf-8'))>s.MAX_BYTES or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():raise ValueError('Invalid reference XML')
    bindings=appearance_xml.namespaces(xml);result=set()
    for node in E.fromstring(xml).iter():
        kind=node.get(values.XSI+'type')
        if kind is not None and values.qname(kind,bindings)==(XR,'DesignTimeRef'):
            if len(node) or set(node.attrib)!={values.XSI+'type'}:raise ValueError('Invalid design-time reference value')
            ref=node.text or '';enum_name(ref);result.add(ref)
    return result


def add_enum(result,body,metadata):
    """EnumRef uses generated type slot 1, not the enum's metadata object UUID."""
    a=s.val
    if (len(body)!=7 or a(body[0])!='1' or a(body[1][0])!='20' or a(metadata[2])!=ids.class_id('Enum')):raise ValueError('Unsupported reference Enum body or class')
    common=body[1][5][1];oid=str(uuid.UUID(a(common[1][2])));name=a(common[2])
    if oid!=a(metadata[1]) or name!=a(metadata[9]):raise ValueError('Enum reference body/metadata identity mismatch')
    type_id=str(uuid.UUID(a(body[1][1])));row=body[6]
    # This group UUID is part of the verified enum layout, not a repository ID.
    from pathlib import Path
    import json
    layout=json.loads(Path(__file__).with_name('enum_layout_851.json').read_text(encoding='utf-8'))
    group=s.Parser(layout['template']).documents()[0][layout['values_slot']][0]
    if a(row[0])!=a(group) or int(a(row[1]))!=len(row)-2:raise ValueError('Invalid enum value collection')
    generated={str(uuid.UUID(a(body[1][slot]))) for slot in layout['generated_slots']}
    if len(generated)!=len(layout['generated_slots']) or oid in generated:raise ValueError('Duplicate enum generated type UUID')
    feature_ids=features(metadata)
    names=set();value_ids=set()
    for item in row[2:]:
        common=item[0][1];value_id=str(uuid.UUID(a(common[1][2])));value_name=a(common[2])
        if not re.fullmatch(r'[^\W\d]\w{0,79}',value_name,re.UNICODE) or value_name.casefold() in names or value_id in value_ids or value_id not in feature_ids or value_id in generated or value_id==oid:raise ValueError('Invalid enum reference value/features')
        names.add(value_name.casefold());value_ids.add(value_id)
        key='Enum.'+name+'.EnumValue.'+value_name
        if key in result:raise ValueError('Ambiguous enum reference: '+key)
        result[key]=(type_id,value_id)
    if value_ids!=feature_ids:raise ValueError('Enum reference feature map differs from value collection')


def features(metadata):
    row=metadata[13]
    if int(s.val(row[0]))!=len(row)-1:raise ValueError('Invalid enum reference features')
    result={str(uuid.UUID(s.val(v))) for v in row[1:]}
    if len(result)!=len(row)-1:raise ValueError('Duplicate enum reference features')
    return result


def objects_for_xml(xml,request):
    refs=required(xml)
    if not refs:return refs,{}
    import constant_serializer as c
    objects=c.context_objects(request['context']);wanted={enum_name(ref) for ref in refs};selected={}
    for oid,docs in objects.items():
        m=docs[0]
        if s.val(m[2])==ids.class_id('Enum') and s.val(m[9]) in wanted:
            name=s.val(m[9])
            if name in selected:raise ValueError('Ambiguous enum in context: '+name)
            selected[name]=(oid,m)
    if set(selected)!=wanted:raise ValueError('Referenced enum is missing from current context')
    return refs,selected


def plan(request):
    _,selected=objects_for_xml(request.get('xml'),request)
    return dict(objects=[dict(object_id=oid,name=s.val(m[9])) for oid,m in sorted(selected.values(),key=lambda item:item[0])])


def resolve(xml,request,storage=None):
    refs,selected=objects_for_xml(xml,request)
    if not refs:return {}
    snapshots=request.get('reference_snapshots',request.get('snapshots',{}));result={}
    for oid,m in selected.values():
        if storage is not None:
            import external_data
            source=external_data.extract(storage,oid)
            if (source['class_id']!=s.val(m[2]) or source['parent_id']!=s.val(m[3]) or source['version_number']!=int(s.val(m[5])) or source['original']!=uuid.UUID(s.val(m[7])).bytes_le.hex() or source['local']!=uuid.UUID(s.val(m[8])).bytes_le.hex()):raise ValueError('Enum version storage/context mismatch')
            raw=s.inflate(base64.b64decode(source['data'],validate=True))
        else:
            if not isinstance(snapshots,dict) or oid not in snapshots:raise ValueError('Referenced enum snapshot is required: '+oid)
            frame=contexts.read(dict(request,snapshot=snapshots[oid]),oid,mismatch_error='Enum reference snapshot/context mismatch')
            if features(frame.saved[0])!=features(frame.metadata):raise ValueError('Enum reference snapshot features mismatch')
            raw=s.inflate(frame.data)
        body=s.Parser(raw.decode('utf-8-sig')).documents()
        if len(body)!=1:raise ValueError('Unsupported enum reference documents')
        add_enum(result,body[0],m)
    if not refs<=result.keys():raise ValueError('Referenced enum value is missing')
    return {ref:result[ref] for ref in refs}


def main():
    from serializer_cli import run
    run(plan)


if __name__=='__main__':main()
