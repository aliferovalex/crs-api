"""Shared native builder for verified managed forms and their parent maps."""
import base64
import copy
import json
import re
import uuid
from pathlib import Path
import metadata_serializer as s
import serialization_context as contexts
import packet_builder as packets
import constant_serializer as c
import metadata_identifiers as identifiers
import platform_profiles as platforms
import managed_form_xml as form_xml
import managed_form_profiles as form_profiles


def create_native(kind,name,platform,owner,definition_xml=None,interface_xml=None,module_text=None,references=None,configuration_id=None):
    """Convert one whole form; packet builders supply its parent metadata."""
    if kind not in form_profiles.KINDS or not platforms.legacy(platform):raise ValueError('Unsupported managed form profile')
    if not isinstance(name,str) or not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE):raise ValueError('Invalid form name')
    fid=str(uuid.uuid4());a=s.atom
    if definition_xml is not None:
        import form_definition_xml
        fid,xml_name,_=form_definition_xml.read(definition_xml,kind,platform)
        if xml_name!=name:raise ValueError('Form name differs from its metadata XML')
    layout=form_profiles.layout(kind)
    form=s.Parser(layout['body_template']).documents();common=form_profiles.common(form[0],kind)
    common[1][2]=a(fid);common[2]=a(name,True)
    raw=s.native_body_bytes(form)
    if definition_xml is not None:raw=form_definition_xml.convert(raw,definition_xml,kind,platform)
    object_type='' if kind=='CommonForm' else c.guid(s.val(owner[1][1]))
    external=b'\xef\xbb\xbf'+layout['external_template'].replace('${catalog_object_type}',object_type).replace('\r\n','\n').replace('\n','\r\n').encode('utf-8')
    paths=form_xml.object_paths(owner,kind);paths.references=references or {}
    external=form_xml.convert(external,interface_xml,module_text,paths,
        form_profiles.owner_name(owner,kind),kind,configuration_id)
    return fid,raw,external


def serialize(request):
    kind=request.get('form_kind','Catalog')
    if kind not in form_profiles.KINDS:raise ValueError('Unsupported managed form kind')
    parent_kind='Configuration' if kind=='CommonForm' else kind
    cls=identifiers.class_id('CommonForm' if kind=='CommonForm' else kind+'Form')
    if not platforms.legacy(request['platform']):raise ValueError('Managed forms require legacy platform profile')
    oid=c.guid(request['object_id']); name=request['name']
    if not isinstance(name,str) or not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE):raise ValueError('Invalid form name')
    frame=contexts.read(request,oid,'Oversized form input','Form parent snapshot/context mismatch');saved,docs,data=frame.saved,frame.docs,frame.data;m=frame.metadata
    if ((s.render(saved[0][12])!="{0}" and sorted(c.children(m))!=sorted(c.children(saved[0]))) or s.metadata_relations(m[14])!=s.metadata_relations(saved[0][14])
            or {s.val(v) for v in m[13][1:]}!={s.val(v) for v in saved[0][13][1:]}):raise ValueError('Parent snapshot/context maps differ')
    for features in (m[13],saved[0][13]):
        if int(s.val(features[0]))!=len(features)-1 or len({s.val(v) for v in features[1:]})!=len(features)-1:raise ValueError('Invalid parent features')
    if s.val(m[2])!=identifiers.class_id(parent_kind) or s.val(m[4])!=s.ZERO:
        raise ValueError('Unsupported form parent')
    packets.preserve_external_versions(copy.deepcopy(saved),oid)
    parent_externals=packets.preserve_external_versions(docs,oid)
    all_context=c.context_objects(request['context'])
    if kind!='CommonForm':
        relations=s.metadata_relations(m[14]);allowed={s.val(m[3])}|{child for child,cls in c.children(m)}
        # Repository metadata retains historical dependencies after deletion.
        # Only absent objects may be historical; live foreign objects remain invalid.
        allowed.update(set(relations)-set(all_context))
        if s.val(m[3])==s.ZERO or relations.get(s.val(m[3]))!=1 or not set(relations).issubset(allowed) or any(v not in (0,1) for v in relations.values()):raise ValueError('Invalid object parent relations')
    if kind=='CommonForm' and s.val(m[3])!=s.ZERO:raise ValueError('Expected Configuration root')
    pairs=c.children(m)
    template_class=identifiers.class_id('Template')
    if kind!='CommonForm' and any(v not in (cls,template_class) for _,v in pairs):raise ValueError('Unsupported existing owner child class')
    for child,child_class in pairs:
        if child not in all_context or s.val(all_context[child][0][2])!=child_class or s.val(all_context[child][0][3])!=oid:raise ValueError('Invalid existing child context')
        if child_class==cls and s.val(all_context[child][0][9]).casefold()==name.casefold():raise ValueError('Form name already exists')
    original=contexts.original_version(request['original_version'],m,'Source parent version mismatch')
    raw=s.inflate(data);body=s.Parser(raw.decode('utf-8-sig')).documents()
    if kind=='CommonForm':s.common_properties(body,oid,request['platform']);object_type=''
    elif kind in ('DataProcessor','Report'):
        import inline_object_xml as inline
        owner_layout=json.loads(Path(__file__).with_name(kind.lower()+'_layout_851.json').read_text(encoding='utf-8'))
        template=s.Parser(owner_layout['template']).documents()[0]
        if len(body)!=1 or len(body[0])!=len(template) or len(body[0][1])!=len(template[1]):raise ValueError('Unsupported form owner layout')
        common=body[0][1][3][1]
        if s.val(common[1][2])!=oid or s.val(common[2])!=s.val(m[9]):raise ValueError('Owner body/description mismatch')
        if set(inline.features(body[0],owner_layout))!={s.val(v) for v in m[13][1:]}:raise ValueError('Owner attributes/features mismatch')
        baseline=copy.deepcopy(body[0]);baseline[1][3][1]=copy.deepcopy(template[1][3][1])
        for slot in owner_layout['generated_slots']:baseline[1][slot]=copy.deepcopy(template[1][slot])
        for profile in owner_layout.get('scalar_properties',{}).values():
            path=profile['path'];baseline[path[0]][path[1]]=copy.deepcopy(template[path[0]][path[1]])
        for path in owner_layout.get('localized_properties',{}).values():baseline[path[0]][path[1]]=copy.deepcopy(template[path[0]][path[1]])
        for profile in owner_layout.get('reference_values',{}).values():
            path=profile['path'];key=s.val(body[0][path[0]][path[1]])
            if key!=s.ZERO and (key,identifiers.class_id(profile['target'])) not in pairs:raise ValueError('Invalid owner form reference')
            baseline[path[0]][path[1]]=copy.deepcopy(template[path[0]][path[1]])
        slot=6 if kind=='DataProcessor' else 5
        baseline[slot]=copy.deepcopy(template[slot])
        import template_serializer
        template_serializer.collection(body,m,all_context)
        template_slot=4 if kind=='DataProcessor' else 3
        baseline[template_slot]=copy.deepcopy(template[template_slot])
        if s.render(baseline)!=s.render(template):raise ValueError('Unsupported form owner properties or children')
        object_type=c.guid(s.val(body[0][1][1]))
    else:
        if len(body)!=1 or len(body[0])!=8 or len(body[0][1])!=(61 if kind=='Catalog' else 53) or s.val(body[0][1][0])!=('57' if kind=='Catalog' else '40'):raise ValueError('Unsupported form owner layout')
        common=body[0][1][9][1]
        if s.val(common[1][2])!=oid or s.val(common[2])!=s.val(m[9]):raise ValueError('Owner body/description mismatch')
        if kind=='Catalog' and (s.val(body[0][1][17])!='9' or s.val(body[0][1][19])!='25' or s.val(body[0][1][18])!='1'):raise ValueError('Only the verified default Catalog attributes are supported')
        if kind=='Document' and s.val(body[0][1][12])!='9':raise ValueError('Only the verified Document number is supported')
        if kind=='Catalog':
            attributes=body[0][6]
            if s.val(attributes[0])!=identifiers.group_id('CatalogAttributes') or int(s.val(attributes[1]))!=len(attributes)-2:raise ValueError('Unsupported Catalog attribute map')
            from catalog_object_xml import inline_features
            attribute_ids=inline_features(body[0])
            if len(set(attribute_ids))!=len(attribute_ids) or set(attribute_ids)!={s.val(v) for v in m[13][1:]}:raise ValueError('Catalog attributes/features mismatch')
        else:
            import inline_object_xml as inline
            layout=json.loads(Path(__file__).with_name('document_layout_851.json').read_text(encoding='utf-8'))
            if set(inline.features(body[0],layout))!={s.val(v) for v in m[13][1:]}:raise ValueError('Document attributes/features mismatch')
        object_type=c.guid(s.val(body[0][1][1]))
    rows=[]
    def walk(node):
        if isinstance(node,list):
            if len(node)>=2 and not isinstance(node[0],list) and s.val(node[0])==cls:rows.append(node)
            for child in node:walk(child)
    walk(body)
    expected={child for child,child_class in pairs if child_class==cls}
    new_position=max((int(s.val(all_context[child][0][10])) for child in expected),default=-1)+1
    if len(rows)!=1 or int(s.val(rows[0][1]))!=len(rows[0])-2 or {s.val(v) for v in rows[0][2:]}!=expected or len(expected)!=len(rows[0])-2:raise ValueError('Form collection/context mismatch')
    import metadata_references
    references=metadata_references.resolve(request.get('form_xml'),request)
    fid,form_raw,external=create_native(kind,name,request['platform'],body[0],request.get('definition_xml'),request.get('form_xml'),request.get('module_text'),references,s.val(m[3]) if kind=='Report' else None)
    a=s.atom
    if fid in all_context:raise ValueError('Form UUID already exists')
    row=rows[0];changed=[row[0],a(len(row)-1)]+list(row[2:])+[a(fid)]
    text=raw.decode('utf-8-sig');new_raw=b'\xef\xbb\xbf'+(text[:row.start]+s.render(changed)+text[row.end:]).encode('utf-8')
    ver=packets.content_version
    versions={oid:ver(new_raw),fid:ver(form_raw)};originals={oid:bytes.fromhex(original),fid:versions[fid]}
    external_version=packets.external_version();external64=base64.b64encode(external_version).decode();external_name=fid+'.0'
    packets.commit_metadata(m,originals[oid],versions[oid])
    class_row=next((v for v in m[12][1:] if s.val(v[0])==cls),None)
    if class_row is None:m[12][0]=a(len(m[12]));m[12].append([a(cls),a(1),a(fid)])
    else:class_row[1]=a(len(class_row)-1);class_row.append(a(fid))
    if kind=='CommonForm':
        count=int(s.val(m[14][0]));m[14]=[a(count+1)]+list(m[14][1:1+count])+[a(fid)]+list(m[14][1+count:])+[a(1)]
    m[15:17]=copy.deepcopy(saved[0][15:17]);docs[1]=copy.deepcopy(saved[1])
    form64=base64.b64encode(versions[fid]).decode()
    fm=[a(6),a(fid),a(cls),a(oid),a(s.ZERO),a(4294967295),a(0),a(form64),a(form64),a(name,True),a(new_position),
        [a(1),a(external_name,True),a(external64)],[a(0)],[a(0)],[a(1),a(oid),a(1)],
        a((s.val(m[15]) if kind!='CommonForm' else '')+cls+'.'+name,True),a(0)]
    fd=[fm,copy.deepcopy(saved[1]),[a(1),[a(external_name,True),a(external64),a(0)]]]
    objects={oid:docs,fid:fd}
    graph=packets.owned_object_creation_graph(objects,oid,fid,pairs+[(fid,cls)])
    payload=packets.assemble(graph,[
        packets.ObjectRecord(fid,s.text_bytes(fd),s.compress(form_raw),((external_name,s.compress(external)),)),
        packets.ObjectRecord(oid,s.text_bytes(docs),s.compress(new_raw))])
    descriptions=[packets.description(objects[key][0],originals[key],versions[key]) for key in (fid,oid)]
    return dict(object_id=fid,data=base64.b64encode(payload).decode(),version_code='',descriptions=descriptions,
        externals=[dict(object_id=fid,name=external_name,version=external_version.hex(),action=0)]+
            [dict(object_id=oid,**stream) for stream in parent_externals])


def main():
    from serializer_cli import run
    run(serialize)


if __name__=='__main__':main()
