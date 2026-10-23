"""Resolve enum values and form reference types from current native metadata."""
import metadata_context
import re
import uuid
from xml.etree import ElementTree as E
import native_metadata as s
import metadata_identifiers as ids
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
    import metadata_targets
    identity=metadata_targets.index({s.val(metadata[1]):[metadata]}).targets[0]
    return add_enum_identity(result,body,identity,features(metadata))


def add_enum_identity(result,body,identity,feature_ids):
    """EnumRef uses generated type slot 1, not the enum's metadata object UUID."""
    a=s.val
    if (len(body)!=7 or a(body[0])!='1' or a(body[1][0])!='20' or identity.class_id!=ids.class_id('Enum')):raise ValueError('Unsupported reference Enum body or class')
    common=body[1][5][1];oid=str(uuid.UUID(a(common[1][2])));name=a(common[2])
    if oid!=identity.object_id or name!=identity.name:raise ValueError('Enum reference body/metadata identity mismatch')
    type_id=str(uuid.UUID(a(body[1][1])));row=body[6]
    # This group UUID is part of the verified enum layout, not a repository ID.
    from pathlib import Path
    import json
    layout=json.loads(Path(__file__).with_name('enum_layout_851.json').read_text(encoding='utf-8'))
    group=s.Parser(layout['template']).documents()[0][layout['values_slot']][0]
    if a(row[0])!=a(group) or int(a(row[1]))!=len(row)-2:raise ValueError('Invalid enum value collection')
    generated={str(uuid.UUID(a(body[1][slot]))) for slot in layout['generated_slots']}
    if len(generated)!=len(layout['generated_slots']) or oid in generated:raise ValueError('Duplicate enum generated type UUID')
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
    objects=metadata_context.context_objects(request['context']);wanted={enum_name(ref) for ref in refs};selected={}
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
    import form_attribute_types
    _,types=form_attribute_types.objects_for_xml(request.get('xml'),request)
    selected_by_id={oid:m for oid,m in list(selected.values())+list(types.values())}
    return dict(objects=[dict(object_id=oid,name=s.val(m[9])) for oid,m in sorted(selected_by_id.items())])


def resolve_values(xml,request,storage=None):
    refs=required(xml)
    if not refs:return {}
    import native_references
    source=native_references.catalog(request);result={}
    for name in {enum_name(ref) for ref in refs}:
        identity=source.select('Enum',name,label='Referenced enum');entry=source.load(identity,storage,label='Enum')
        body=s.Parser(entry.body.decode('utf-8-sig')).documents()
        if len(body)!=1:raise ValueError('Unsupported enum reference documents')
        add_enum_identity(result,body[0],identity,entry.features)
    if not refs<=result.keys():raise ValueError('Referenced enum value is missing')
    return {ref:result[ref] for ref in refs}


def resolve(xml,request,storage=None):
    import form_attribute_types
    result=resolve_values(xml,request,storage)
    result.update(form_attribute_types.resolve(xml,request,storage))
    return result


def form_relations(xml,request,parent,previous,raw=None,storage=None):
    """Reconcile proven form type dependencies, retaining opaque relations."""
    import form_attribute_types,native_references
    result=dict(previous);reader=native_references.catalog(request)
    names={('Enum',enum_name(ref)) for ref in required(xml)}
    names.update(form_attribute_types.reference_name(ref) for ref in form_attribute_types.required(xml))
    final={reader.select(*name,label='Referenced form type').object_id for name in names}
    if raw is not None:
        # Source dependencies must be checked against source versions, including
        # objects removed from the final declaration index in this commit.
        source=native_references.Catalog(request);atoms=set()
        def visit(node):
            if isinstance(node,list):
                for child in node:visit(child)
            elif not node.quoted:atoms.add(s.val(node))
        import managed_form_xml
        visit(managed_form_xml.interface(raw))
        for oid,flag in previous.items():
            if oid==parent or oid in final or flag!=1 or oid not in source.source:continue
            identity=next(row for row in source.targets.targets if row.object_id==oid)
            kind=ids.class_labels().get(identity.class_id)
            if kind not in form_attribute_types.KINDS.values():continue
            generated=source.type_id(kind,identity.name,storage=storage)
            if generated in atoms:result.pop(oid)
    result[parent]=1
    for oid in sorted(final):
        if oid!=parent:result[oid]=1
    return [s.atom(len(result))]+[s.atom(key) for key in result]+[s.atom(flag) for flag in result.values()]


def main():
    from serializer_cli import run
    run(plan)


if __name__=='__main__':main()
