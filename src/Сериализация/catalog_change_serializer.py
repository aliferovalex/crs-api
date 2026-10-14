"""Serialize complete Catalog XML: properties, inline children and form references."""
import json,re,uuid
from pathlib import Path
from xml.etree import ElementTree as E
import metadata_serializer as s
import serialization_context as contexts
import packet_builder as packets
import metadata_identifiers as ids
import platform_profiles as platforms
import constant_serializer as c


def serialize(request):
    if not platforms.legacy(request['platform']):raise ValueError('Catalog attributes require legacy platform profile')
    oid=c.guid(request['object_id']);name=request.get('name');length=request.get('length')
    if 'object_xml' not in request and (not isinstance(name,str) or not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE)):raise ValueError('Invalid attribute name')
    if 'object_xml' not in request and (type(length)!=int or not 1<=length<=1024):raise ValueError('String length must be 1..1024')
    frame=contexts.read(request,oid,'Oversized attribute input');saved,docs,data=frame.saved,frame.docs,frame.data;m=frame.metadata
    if s.val(m[2])!=ids.class_id('Catalog') or s.val(m[3])==s.ZERO or s.val(m[4])!=s.ZERO or s.render(m[11])!='{0}' or s.render(docs[2])!='{0}' or s.render(saved[2])!='{0}':raise ValueError('Unsupported Catalog metadata')
    pairs=c.children(m)
    if any(cls!=ids.class_id('CatalogForm') for child,cls in pairs):raise ValueError('Only forms are supported as existing children')
    if s.metadata_relations(m[14])!=s.metadata_relations(saved[0][14]):raise ValueError('Snapshot/context relations differ')
    features={s.val(v) for v in m[13][1:]}
    for group in (m[13],saved[0][13]):
        if int(s.val(group[0]))!=len(group)-1 or {s.val(v) for v in group[1:]}!=features or len(features)!=len(group)-1:raise ValueError('Invalid attribute feature map')
    original=contexts.original_version(request['original_version'],m,'Source version mismatch')
    raw=s.inflate(data);body=s.Parser(raw.decode('utf-8-sig')).documents()
    if len(body)!=1 or len(body[0])!=8 or len(body[0][1])!=61 or s.val(body[0][1][0])!='57':raise ValueError('Unsupported Catalog body')
    common=body[0][1][9][1]
    if s.val(common[1][2])!=oid or s.val(common[2])!=s.val(m[9]):raise ValueError('Catalog body/description mismatch')
    row=body[0][6]
    if s.val(row[0])!=ids.group_id('CatalogAttributes') or int(s.val(row[1]))!=len(row)-2:raise ValueError('Unsupported attribute collection')
    existing=[]
    for item in row[2:]:
        props=item[0][1][1][1];existing.append(c.guid(s.val(props[1][2])))
        if 'object_xml' not in request and s.val(props[2]).casefold()==name.casefold():raise ValueError('Attribute name already exists')
    import catalog_object_xml
    all_existing=catalog_object_xml.inline_features(body[0])
    if set(all_existing)!=features:raise ValueError('Attribute collection/features mismatch')
    objects=c.context_objects(request['context'])
    for child,cls in pairs:
        if child not in objects or s.val(objects[child][0][2])!=cls or s.val(objects[child][0][3])!=oid:raise ValueError('Invalid Catalog child context')
    forms={s.val(objects[child][0][9]):child for child,cls in pairs}
    if len(forms)!=len(pairs):raise ValueError('Duplicate Catalog form name')
    aid=None
    if 'object_xml' in request:
        target_xml=request['object_xml']
    else:
        # The compatibility operation builds the desired complete XML first.
        aid=str(uuid.uuid4());entry=s.Parser(json.loads(Path(__file__).with_name('catalog_attribute_layout_851.json').read_text(encoding='utf-8'))['template']).documents()[0]
        common=entry[0][1][1][1];common[1][2]=s.atom(aid);common[2]=s.atom(name,True)
        entry[0][1][1][2][1][1]=s.atom(length)
        top=catalog_object_xml.export(body[0],forms,request['platform'])
        top[0].find('{'+c.MD+'}ChildObjects').append(catalog_object_xml.attribute_export(entry))
        target_xml=E.tostring(top,encoding='unicode')
    new_raw,new_ids=catalog_object_xml.convert(target_xml,request['platform'],body[0],forms)
    a=s.atom
    m[13]=[a(len(new_ids))]+[a(v) for v in new_ids]
    relations=s.metadata_relations(m[14]);relations.update({child:1 for child,cls in pairs})
    m[14]=[a(len(relations))]+[a(v) for v in relations]+[a(v) for v in relations.values()]
    xml=packets.pack_body_change(request,docs,saved,new_raw,original,pairs,
        descriptor_order=[('name',9),('pos',10),('parentID',3),('ownerID',4),('verNum',None),('selfVerNum',None)])
    result=dict(request_xml=xml)
    if aid is not None:result['attribute_id']=aid
    return result


def main():
    from serializer_cli import run
    run(serialize)


if __name__=='__main__':main()
