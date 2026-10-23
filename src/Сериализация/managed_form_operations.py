"""Managed form operations: creation/change checks, streams and commit packets."""
import configuration_xml
import metadata_context
import base64
import copy
import re
import uuid
import native_metadata as s
import serialization_context as contexts
import packet_builder as packets
import metadata_identifiers as identifiers
import platform_profiles as platforms
import managed_form_xml as form_xml
import external_data
import native_content
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
    object_type='' if kind=='CommonForm' or kind not in ('Catalog','Document','DataProcessor','Report') else metadata_context.guid(s.val(owner[1][1]))
    external=b'\xef\xbb\xbf'+layout['external_template'].replace('${catalog_object_type}',object_type).replace('\r\n','\n').replace('\n','\r\n').encode('utf-8')
    paths=form_xml.object_paths(owner,kind);paths.references=references or {}
    external=form_xml.convert(external,interface_xml,module_text,paths,
        form_profiles.owner_name(owner,kind),kind,configuration_id)
    return fid,raw,external


def create(request,*,owner_body=None,contents_only=False):
    kind=request.get('form_kind','Catalog')
    if kind not in form_profiles.KINDS:raise ValueError('Unsupported managed form kind')
    parent_kind='Configuration' if kind=='CommonForm' else kind
    cls=identifiers.class_id('CommonForm' if kind=='CommonForm' else kind+'Form')
    if not platforms.legacy(request['platform']):raise ValueError('Managed forms require legacy platform profile')
    oid=metadata_context.guid(request['object_id']); name=request['name']
    if not isinstance(name,str) or not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE):raise ValueError('Invalid form name')
    frame=contexts.read(request,oid,'Oversized form input','Form parent snapshot/context mismatch');saved,docs,data=frame.saved,frame.docs,frame.data;m=frame.metadata
    if ((s.render(saved[0][12])!="{0}" and sorted(metadata_context.children(m))!=sorted(metadata_context.children(saved[0]))) or s.metadata_relations(m[14])!=s.metadata_relations(saved[0][14])
            or {s.val(v) for v in m[13][1:]}!={s.val(v) for v in saved[0][13][1:]}):raise ValueError('Parent snapshot/context maps differ')
    for features in (m[13],saved[0][13]):
        if int(s.val(features[0]))!=len(features)-1 or len({s.val(v) for v in features[1:]})!=len(features)-1:raise ValueError('Invalid parent features')
    if s.val(m[2])!=identifiers.class_id(parent_kind) or s.val(m[4])!=s.ZERO:
        raise ValueError('Unsupported form parent')
    raw=s.inflate(data);body=s.Parser(raw.decode('utf-8-sig')).documents()
    if len(body)!=1:raise ValueError('Unsupported native owner documents')
    import inline_command_xml
    inline_command_xml.preserve_owner_streams(copy.deepcopy(saved),oid,body[0],parent_kind,request['platform'])
    parent_externals=inline_command_xml.preserve_owner_streams(docs,oid,body[0],parent_kind,request['platform'])
    all_context=metadata_context.context_objects(request['context'])
    if kind!='CommonForm':
        relations=s.metadata_relations(m[14]);allowed={s.val(m[3])}|{child for child,cls in metadata_context.children(m)}
        # Repository metadata retains historical dependencies after deletion.
        # Only absent objects may be historical; live foreign objects remain invalid.
        allowed.update(set(relations)-set(all_context))
        if set(relations)-allowed and kind in ('Catalog','DataProcessor','Report'):
            import metadata_type_references,object_xml_profiles
            proven=metadata_type_references.source_owners(request,body[0],object_xml_profiles.layout(kind,request['platform']),relations,oid,strict=False)
            allowed.update(key for key in proven if relations.get(key)==0)
        if kind not in ('Catalog','DataProcessor','Report'):allowed.update(relations)
        if s.val(m[3])==s.ZERO or relations.get(s.val(m[3]))!=1 or not set(relations).issubset(allowed) or any(v not in (0,1) for v in relations.values()):raise ValueError('Invalid object parent relations: '+kind)
    if kind=='CommonForm' and s.val(m[3])!=s.ZERO:raise ValueError('Expected Configuration root')
    pairs=metadata_context.children(m)
    template_class=identifiers.class_id('Template')
    if kind in ('Catalog','Document','DataProcessor','Report') and any(v not in (cls,template_class) for _,v in pairs):raise ValueError('Unsupported existing owner child class')
    for child,child_class in pairs:
        if child not in all_context or s.val(all_context[child][0][2])!=child_class or s.val(all_context[child][0][3])!=oid:raise ValueError('Invalid existing child context')
        if child_class==cls and s.val(all_context[child][0][9]).casefold()==name.casefold():raise ValueError('Form name already exists')
    original=contexts.original_version(request['original_version'],m,'Source parent version mismatch')
    if kind=='CommonForm':configuration_xml.common_properties(body,oid,request['platform'])
    else:
        common=form_profiles.owner_common(body[0],kind)
        if s.val(common[1][2])!=oid or s.val(common[2])!=s.val(m[9]):raise ValueError('Owner body/description mismatch')
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
    storage=contexts.decode(request['storage'],'Oversized form input') if 'storage' in request else None
    references=metadata_references.resolve(request.get('form_xml'),request,storage)
    binding_owner=form_profiles.binding_owner(body[0],owner_body,kind,allow_rename=request.get('_allow_owner_rename',False))
    fid,form_raw,external=create_native(kind,name,request['platform'],binding_owner,request.get('definition_xml'),request.get('form_xml'),request.get('module_text'),references,s.val(m[3]) if kind=='Report' else None)
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
    fm[14]=metadata_references.form_relations(request.get('form_xml'),request,oid,{oid:1})
    fd=[fm,copy.deepcopy(saved[1]),[a(1),[a(external_name,True),a(external64),a(0)]]]
    objects={oid:docs,fid:fd}
    if contents_only:
        return native_content.CreationContent({fid:native_content.ObjectContent(
            fd,form_raw,[(external_name,s.compress(external))],
            [dict(name=external_name,version=external_version.hex(),action=0)])},'')
    graph=packets.owned_object_creation_graph(objects,oid,fid,pairs+[(fid,cls)])
    payload=packets.assemble(graph,[
        packets.ObjectRecord(fid,s.text_bytes(fd),s.compress(form_raw),((external_name,s.compress(external)),)),
        packets.ObjectRecord(oid,s.text_bytes(docs),s.compress(new_raw))])
    descriptions=[packets.description(objects[key][0],originals[key],versions[key]) for key in (fid,oid)]
    return dict(object_id=fid,data=base64.b64encode(payload).decode(),version_code='',descriptions=descriptions,
        externals=[dict(object_id=fid,name=external_name,version=external_version.hex(),action=0)]+
            [dict(object_id=oid,**stream) for stream in parent_externals])


def compile_change(request,*,owner_body=None):
    if not platforms.legacy(request['platform']):raise ValueError('Managed form changes require legacy profile')
    oid=str(uuid.UUID(request['object_id']))
    if 'attribute_name' in request:raise ValueError('Partial attribute insertion is unsupported; supply complete Form.xml')
    if 'module_text' in request and not isinstance(request['module_text'],str):raise ValueError('Invalid form module text')
    if 'form_xml' in request and not isinstance(request['form_xml'],str):raise ValueError('Complete Form.xml must be text')
    if 'form_xml' not in request and 'module_text' not in request and not request.get('preserve_content'):raise ValueError('Complete Form.xml or module_text is required')
    storage=contexts.decode(request['storage'],'Oversized form input')
    frame=contexts.read(request,oid,'Oversized form input','Form snapshot/context mismatch');saved,docs,data=frame.saved,frame.docs,frame.data;m=frame.metadata
    kind=identifiers.class_labels().get(s.val(m[2]))
    kinds={('CommonForm' if owner=='CommonForm' else owner+'Form'):owner for owner in form_profiles.KINDS}
    if kind not in kinds or s.val(m[4])!=s.ZERO or any(s.render(m[i])!='{0}' for i in (12,13)):raise ValueError('Unsupported form metadata')
    owner_kind=kinds[kind]
    parent_id=s.val(m[3]);name=oid+'.0';refs=m[11]
    relations=s.metadata_relations(m[14])
    if relations.get(parent_id)!=1 or relations!=s.metadata_relations(saved[0][14]) or len(refs)!=3 or s.val(refs[1])!=name:raise ValueError('Unsupported form source stream or relations')
    original=contexts.original_version(request['original_version'],m,'Source version mismatch')
    current=external_data.extract(storage,oid);parent=external_data.extract(storage,parent_id)
    if (current['class_id']!=s.val(m[2]) or current['parent_id']!=parent_id or current['version_number']!=int(s.val(m[5]))
            or current['original']!=original[:32] or current['local']!=uuid.UUID(s.val(m[8])).bytes_le.hex()
            or parent['class_id']!=identifiers.class_id('Configuration' if owner_kind=='CommonForm' else owner_kind) or len(current['externals'])!=1):raise ValueError('Version storage/snapshot mismatch')
    stream=current['externals'][0]
    if stream['name']!=name or stream['version']!=uuid.UUID(s.val(refs[2])).bytes_le.hex()+'00000000':raise ValueError('External source version mismatch')
    body=s.inflate(data)
    definition=s.Parser(body.decode('utf-8-sig')).documents()[0]
    common=form_profiles.common(definition,owner_kind)
    if s.val(common[1][2])!=oid or s.val(common[2])!=s.val(m[9]):raise ValueError('Form body/description mismatch')
    if 'definition_xml' in request:
        import form_definition_xml
        body=form_definition_xml.convert(body,request['definition_xml'],owner_kind,request['platform'],allow_rename=request.get('_allow_rename',False))
        m[9]=copy.deepcopy(form_profiles.common(s.Parser(body.decode('utf-8-sig')).documents()[0],owner_kind)[2])
    if request.get('preserve_content'):
        return native_content.body_change(docs,saved,body,oid)
    owner=s.Parser(s.inflate(base64.b64decode(parent['data'],validate=True)).decode('utf-8-sig')).documents()[0]
    binding_owner=form_profiles.binding_owner(owner,owner_body,owner_kind,allow_rename=request.get('_allow_owner_rename',False))
    raw=s.inflate(base64.b64decode(stream['data'],validate=True))
    if 'form_xml' in request:
        import metadata_references
        paths=form_xml.object_paths(binding_owner,owner_kind)
        paths.references=metadata_references.resolve(request['form_xml'],request,storage)
        form=form_xml.interface(raw)
        if paths.main_types:
            for entry in form[3][2:2+int(s.val(form[3][1]))]:
                if s.val(entry[10])=='1' and (len(entry[5])!=2 or len(entry[5][1])!=2 or s.val(entry[5][1][0])!='#' or s.val(entry[5][1][1]) not in paths.main_types.values()):raise ValueError('Form main attribute type mismatch')
        external=form_xml.convert(raw,request['form_xml'],request.get('module_text'),
            paths,form_profiles.owner_name(binding_owner,owner_kind),owner_kind,parent['parent_id'] if owner_kind=='Report' else None)
        m[14]=metadata_references.form_relations(request['form_xml'],request,parent_id,relations,raw,storage)
    else:
        external=form_xml.convert(raw,module_text=request['module_text'])
    return native_content.external_change(docs,saved,body,name,s.compress(external),packets.external_version())


def change(request,*,owner_body=None):
    return packets.pack_external_change(compile_change(request,owner_body=owner_body),request['original_version'].lower())

def serialize(request,*,owner_body=None):
    """Explicit operation dispatch for the common OneScript JSON bridge."""
    operation=request.get('operation')
    if operation=='Создание':return create(request,owner_body=owner_body)
    if operation=='Изменение':return change(request,owner_body=owner_body)
    raise ValueError('Managed form operation must be Создание or Изменение')


def main():
    from serializer_cli import run
    run(serialize)


if __name__=='__main__':main()
