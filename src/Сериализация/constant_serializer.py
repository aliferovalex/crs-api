"""Experimental flat Configuration and supported top-level object creation.

Input is fresh server snapshots/context and object XML. No capture, CF, network
or Designer is used. Native layout is deliberately limited to verified defaults.
"""
import base64
import copy
import json
import re
import uuid
import xml.etree.ElementTree as E
from pathlib import Path
import metadata_serializer as s
import type_description_xml as types
import packet_builder as packets
import metadata_identifiers as identifiers
import platform_profiles as platforms
import object_xml_profiles as profiles
import object_graph

CLASS = identifiers.class_id('Constant')
LANGUAGE = identifiers.class_id('Language')
MD = 'http://v8.1c.ru/8.3/MDClasses'
CORE = 'http://v8.1c.ru/8.1/data/core'
READABLE = 'http://v8.1c.ru/8.3/xcf/readable'
# Verified native layout for a string constant with default editing/choice/history.
TEMPLATE = ('{1,{16,{27,{2,{4,{1,0,00000000-0000-0000-0000-000000000000},"",'
            '{0},"",0,0,00000000-0000-0000-0000-000000000000,0,0,3},'
            '{"Pattern",{"S",100,1}}},0,{0},{0},0,"",0,{"U"},{"U"},0,'
            '00000000-0000-0000-0000-000000000000,2,0,{5006,0},{3,0,0},{0,0},0,'
            '{0},{"S",""},0,0,0},'
            '00000000-0000-0000-0000-000000000000,00000000-0000-0000-0000-000000000000,'
            '00000000-0000-0000-0000-000000000000,00000000-0000-0000-0000-000000000000,'
            '1,1,{0},{0},00000000-0000-0000-0000-000000000000,0,0,'
            '00000000-0000-0000-0000-000000000000,00000000-0000-0000-0000-000000000000,0,0},0}')
DEFAULTS = {
    'UseStandardCommands':'true','DefaultForm':'','ExtendedPresentation':'','Explanation':'',
    'PasswordMode':'false','Format':'','EditFormat':'','ToolTip':'','MarkNegatives':'false',
    'Mask':'','MultiLine':'false','ExtendedEdit':'false','MinValue':'','MaxValue':'',
    'FillChecking':'DontCheck','ChoiceFoldersAndItems':'Items','ChoiceParameterLinks':'',
    'ChoiceParameters':'','QuickChoice':'Auto','ChoiceForm':'','LinkByType':'',
    'ChoiceHistoryOnInput':'Auto','DataLockControlMode':'Managed','DataHistory':'DontUse',
    'UpdateDataHistoryImmediatelyAfterWrite':'false','ExecuteAfterWriteDataHistoryVersionProcessing':'false'}

def guid(value):
    result = str(uuid.UUID(value))
    if result == s.ZERO:
        raise ValueError('Zero UUID is forbidden')
    return result

def context_objects(encoded):
    if not isinstance(encoded,str) or len(encoded)>s.MAX_BYTES*2:
        raise ValueError('Oversized or invalid context')
    data = base64.b64decode(encoded, validate=True)
    s.validate_storage(data)
    pos, objects = 12, {}
    while pos < len(data):
        raw, pos = s.read_record(data, pos)
        if not raw.startswith(b'\xef\xbb\xbf{5,'):
            break
        docs = s.Parser(raw.decode('utf-8-sig')).documents()
        m = docs[0]
        if len(docs) != 3 or len(m) != 17 or s.val(m[0]) != '5':
            raise ValueError('Unsupported context metadata')
        oid = guid(s.val(m[1]))
        if oid in objects:
            raise ValueError('Duplicate context UUID')
        objects[oid] = docs
    return objects

def children(metadata):
    result = []
    group = metadata[12]
    if int(s.val(group[0])) != len(group)-1:
        raise ValueError('Invalid child class map')
    for row in group[1:]:
        if int(s.val(row[1])) != len(row)-2:
            raise ValueError('Invalid child class count')
        result.extend((guid(s.val(oid)), s.val(row[0])) for oid in row[2:])
    if len({oid for oid, _ in result}) != len(result):
        raise ValueError('Duplicate child UUID')
    return result

def inspect(request):
    objects = context_objects(request['context'])
    oid = guid(request['object_id'])
    m = objects[oid][0]
    if s.val(m[2]) != s.ROOT_CLASS or s.val(m[3]) != s.ZERO:
        raise ValueError('Configuration root required')
    return [child for child in object_graph.closure(objects,oid,children) if child!=oid]

def constant_xml(text, platform='8.5.4.1878'):
    platforms.profile(platform)
    if not isinstance(text, str) or len(text.encode('utf-8')) > s.MAX_BYTES:
        raise ValueError('Oversized Constant XML')
    if '<!DOCTYPE' in text.upper():raise ValueError('DOCTYPE is unsupported')
    top = E.fromstring(text)
    if top.tag != '{%s}MetaDataObject'%MD or len(top) != 1 or top[0].tag != '{%s}Constant'%MD:
        raise ValueError('Expected MetaDataObject/Constant XML')
    if not platforms.xml_attributes(top.attrib, platform):raise ValueError('Unsupported XML version or attributes')
    constant = top[0]; oid = guid(constant.attrib['uuid'])
    if constant.attrib != {'uuid':constant.attrib['uuid']}:raise ValueError('Unsupported Constant attributes')
    if len({n.tag for n in constant}) != len(constant):
        raise ValueError('Duplicate Constant XML section')
    if any(n.tag not in ('{%s}Properties'%MD,'{%s}InternalInfo'%MD) for n in constant):
        raise ValueError('Unsupported Constant XML section')
    props = constant.find('{%s}Properties'%MD)
    if props is None or len({n.tag for n in props}) != len(props):
        raise ValueError('Missing or duplicate Constant properties')
    if props.attrib:raise ValueError('Unsupported Properties attributes')
    fields = {n.tag.removeprefix('{%s}'%MD):n for n in props}
    if any(n.tag != '{%s}%s'%(MD,key) for key,n in fields.items()):
        raise ValueError('Unexpected property namespace')
    def value(key):return fields[key].text or ''
    name = value('Name')
    if not re.fullmatch(r'[^\W\d]\w{0,79}',name, re.UNICODE):
        raise ValueError('Invalid Constant name')
    for key,node in fields.items():
        if key in ('Name','Comment','Synonym','Type'):continue
        if key not in DEFAULTS or (node.text or '') != DEFAULTS[key] or len(node):
            raise ValueError('Unsupported Constant property: '+key)
        permitted = {'{http://www.w3.org/2001/XMLSchema-instance}nil':'true'} if key in ('MinValue','MaxValue') else {}
        if node.attrib and node.attrib != permitted:
            raise ValueError('Unsupported property attributes: '+key)
    for key in ('Name','Comment'):
        if key in fields and (len(fields[key]) or fields[key].attrib):
            raise ValueError('Invalid text property')
    synonyms = []
    if 'Synonym' in fields:
        if fields['Synonym'].attrib:raise ValueError('Unsupported Synonym attributes')
        for item in fields['Synonym']:
            if item.tag != '{%s}item'%CORE or [n.tag for n in item] != ['{%s}lang'%CORE,'{%s}content'%CORE]:
                raise ValueError('Unsupported Synonym')
            if item.attrib or any(n.attrib or len(n) for n in item):raise ValueError('Unsupported Synonym structure')
            lang, content = (n.text or '' for n in item)
            if not re.fullmatch('[a-zA-Z][a-zA-Z0-9_-]*',lang) or lang in [pair[0] for pair in synonyms]:
                raise ValueError('Invalid or duplicate Synonym language')
            synonyms.append((lang,content))
    pattern=types.read(fields.get('Type'))
    if not platforms.legacy(platform) and s.val(pattern[1][0])!='S':
        raise ValueError('Non-string scalar types require the verified legacy profile')
    docs = s.Parser(TEMPLATE).documents();native = docs[0][1];common = native[1][1][1]
    if platforms.legacy(platform):
        common[0] = s.atom(3)
        del common[9:]
    common[1][2],common[2],common[4] = s.atom(oid),s.atom(name,True),s.atom(value('Comment') if 'Comment' in fields else '',True)
    common[3] = [s.atom(len(synonyms))]
    for lang,content in synonyms:common[3].extend([s.atom(lang,True),s.atom(content,True)])
    native[1][1][2] = pattern
    internal = constant.find('{%s}InternalInfo'%MD)
    ids=[]
    if internal is not None:
        expected = [('ConstantManager.','Manager'),('ConstantValueManager.','ValueManager'),('ConstantValueKey.','ValueKey')]
        if len(internal)!=3 or internal.attrib:raise ValueError('Expected three generated types')
        for node,(prefix,category) in zip(internal,expected):
            if node.tag != '{%s}GeneratedType'%READABLE or node.attrib != {'name':prefix+name,'category':category} or [n.tag for n in node] != ['{%s}TypeId'%READABLE,'{%s}ValueId'%READABLE]:
                raise ValueError('Unsupported generated type')
            ids.extend(guid(n.text) for n in node)
            if any(n.attrib or len(n) for n in node):raise ValueError('Unsupported generated UUID structure')
    else:ids=[str(uuid.uuid4()) for _ in range(6)]
    if len(set(ids+[oid]))!=7:raise ValueError('Duplicate generated UUID')
    for index,value_ in zip((2,3,4,5,13,14),ids):native[index]=s.atom(value_)
    return oid,name,s.native_body_bytes(docs),ids

def serialize(request):
    kind = request.get("object_type", "Constant")
    if kind not in profiles.creation_types():raise ValueError("Unsupported creation type")
    object_class = identifiers.class_id(kind)
    platforms.profile(request['platform'])
    rid=guid(request['object_id']);objects=context_objects(request['context']);root=objects[rid]
    existing_order=inspect(request)
    oldchildren=children(root[0]);expected={rid}|set(existing_order)
    if not platforms.legacy(request['platform']) and expected!={rid}|{oid for oid,_ in oldchildren}:raise ValueError('Modern profile requires a flat object tree')
    allowed_classes = (CLASS,LANGUAGE) + (tuple(identifiers.class_id(v) for v in profiles.profiles()) if platforms.legacy(request['platform']) else ())
    if not platforms.legacy(request['platform']) and any(cls not in allowed_classes for _,cls in oldchildren):
        raise ValueError('Only a flat Configuration with verified object profiles is supported')
    if set(request['snapshots'])!=expected:raise ValueError('Snapshots must cover the complete object and dependency graph')
    if any(not isinstance(v,str) for v in request['snapshots'].values()) or sum(len(v) for v in request['snapshots'].values())>s.MAX_BYTES*2:
        raise ValueError('Oversized or invalid snapshots')
    form_inputs=request.get('forms',[]);new_forms=[];form_names={}
    if not isinstance(form_inputs,list) or len(form_inputs)>256 or (form_inputs and kind!='Catalog'):raise ValueError('Invalid creation forms')
    for entry in form_inputs:
        if not isinstance(entry,dict) or set(entry)!={'name','definition_xml','form_xml','module_text'}:raise ValueError('Invalid creation form files')
        import form_definition_xml
        fid,fname,_=form_definition_xml.read(entry['definition_xml'],'Catalog',request['platform'])
        if fname!=entry['name'] or fname.casefold() in {n.casefold() for n in form_names} or fid in form_names.values():raise ValueError('Duplicate or mismatched creation form')
        if not isinstance(entry['form_xml'],str):raise ValueError('Creation form requires complete Form.xml')
        form_names[fname]=fid
    if sum(len(json.dumps(entry).encode('utf-8')) for entry in form_inputs)>s.MAX_BYTES:raise ValueError('Oversized creation forms')
    if kind!='Constant':
        if kind=='Catalog':
            from catalog_object_xml import create
            cid,name,body,generated=create(request['catalog_xml'],request['platform'],form_names)
            if form_inputs:
                import managed_form_serializer
                owner=s.Parser(body.decode('utf-8-sig')).documents()[0]
                for entry in form_inputs:
                    import metadata_references
                    references=metadata_references.resolve(entry['form_xml'],request)
                    fid,form_body,external=managed_form_serializer.create_native('Catalog',entry['name'],request['platform'],owner,entry['definition_xml'],entry['form_xml'],entry['module_text'],references)
                    new_forms.append((fid,entry['name'],form_body,external))
                generated+=list(form_names.values())
                if len(set(generated+[cid]))!=len(generated)+1:raise ValueError('Duplicate Catalog, inline or form UUID')
        else:
            from flat_object_serializer import object_xml
            cid,name,body,generated=object_xml(request[kind.lower()+'_xml'], request['platform'],kind,objects)
    else:
        cid,name,body,generated=constant_xml(request['constant_xml'], request['platform'])
    if cid in objects or any(s.val(objects[oid][0][9]).casefold()==name.casefold() for oid,cls in oldchildren if cls==object_class):
        raise ValueError(f'{kind} UUID or name already exists')
    known=set(objects)
    if any(g in known for g in generated):raise ValueError('Generated type UUID collides with an object')
    raws={};versions={};originals={};externals={};external_data={};inline_streams=[]
    for oid in sorted(expected):
        data=base64.b64decode(request['snapshots'][oid],validate=True);s.validate_storage(data)
        meta,pos=s.read_record(data,12);content,pos=s.read_record(data,pos)
        saved=s.Parser(meta.decode('utf-8-sig')).documents()[0];m=objects[oid][0]
        if [s.render(saved[i]) for i in range(12)] != [s.render(m[i]) for i in range(12)]:
            raise ValueError('Snapshot/context mismatch')
        for features in (saved[13],m[13]):
            if int(s.val(features[0]))!=len(features)-1 or len({s.val(v) for v in features[1:]})!=len(features)-1:
                raise ValueError('Invalid metadata features')
        if {s.val(v) for v in saved[13][1:]}!={s.val(v) for v in m[13][1:]} or s.metadata_relations(saved[14])!=s.metadata_relations(m[14]):
            raise ValueError('Snapshot/context relations or features mismatch')
        m[15:17]=copy.deepcopy(saved[15:17])
        refs=m[11]
        # updateInfo lists external versions to retrieve; commit includes only
        # newly supplied streams. Existing streams remain stored on the server.
        owned={}
        if s.render(refs)!='{0}':
            object_kind=identifiers.class_labels().get(s.val(m[2]))
            if object_kind in profiles.profiles():
                import inline_command_xml as commands
                layout=json.loads(Path(__file__).with_name(object_kind.lower()+'_layout_851.json').read_text(encoding='utf-8'))
                if layout.get('command_collections'):owned=commands.streams(s.Parser(s.inflate(content).decode('utf-8-sig')).documents()[0],layout)
            inline_streams.extend(dict(object_id=oid,name=stream) for stream in owned.values())
        preserved=packets.preserve_external_versions(objects[oid],oid,owned.values())
        if preserved:externals[oid]=preserved
        if s.val(m[4])!=s.ZERO:raise ValueError('Owned objects unsupported')
        originals[oid]=uuid.UUID(s.val(m[7])).bytes_le+bytes(4)
        raws[oid]=s.inflate(content)
        versions[oid]=packets.content_version(raws[oid],uuid.UUID(s.val(m[8])))
    for metadata in objects.values():known.update(re.findall(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', s.render(metadata).lower()))
    for raw in raws.values():known.update(re.findall(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',raw.decode('utf-8-sig').lower()))
    if any(g in known for g in generated+[cid]):raise ValueError('New UUID collides with existing native data')
    text=raws[rid].decode('utf-8-sig');docs=s.Parser(text).documents()
    matches=[]
    def walk(node):
        if isinstance(node,list):
            if len(node)>=2 and not isinstance(node[0],list) and s.val(node[0])==object_class:
                matches.append(node)
            for sub in node:walk(sub)
    walk(docs)
    if len(matches)!=1:raise ValueError(f'{kind} class map not found uniquely in root')
    row=matches[0]
    if {s.val(v) for v in row[2:]}!={oid for oid,cls in oldchildren if cls==object_class} or int(s.val(row[1]))!=len(row)-2 or len({s.val(v) for v in row[2:]})!=len(row)-2:
        raise ValueError(f'Root content/context {kind} map differs')
    updated=[row[0],s.atom(len(row)-1)]+list(row[2:])+[s.atom(cid)]
    # Positions follow the native collection order, not the context-map order.
    # Earlier packages assigned position 0 to every newly created Constant.
    # Designer normalizes these duplicate positions on retrieval.
    constant_positions={s.val(node):index for index,node in enumerate(updated[2:])}
    # Existing descriptors must stay identical to their source descriptions.
    # Previously stored duplicate positions require a separate native repair.
    raws[rid]=b'\xef\xbb\xbf'+(text[:row.start]+s.render(updated)+text[row.end:]).encode('utf-8')
    versions[rid]=packets.content_version(raws[rid])
    versions[cid]=packets.content_version(body);originals[cid]=versions[cid];raws[cid]=body
    rm=root[0];rmap=rm[12];constrow=next((r for r in rmap[1:] if s.val(r[0])==object_class),None)
    if constrow is None:rmap[0]=s.atom(len(rmap));rmap.append([s.atom(object_class),s.atom(1),s.atom(cid)])
    else:constrow[1]=s.atom(len(constrow)-1);constrow.append(s.atom(cid))
    # Native relation arrays are column-wise: all UUIDs, then all flags.
    count=int(s.val(rm[14][0]));relationids=list(rm[14][1:1+count]);flags=list(rm[14][1+count:])
    if len(flags)!=count or not {oid for oid,_ in oldchildren}.issubset({s.val(n) for n in relationids}):
        raise ValueError('Invalid root relation columns')
    rm[14]=[s.atom(count+1)]+relationids+[s.atom(cid)]+flags+[s.atom(1)]
    original64=base64.b64encode(originals[cid]).decode()
    cm=[s.atom(6),s.atom(cid),s.atom(object_class),s.atom(rid),s.atom(s.ZERO),s.atom(4294967295),s.atom(0),s.atom(original64),s.atom(original64),s.atom(name,True),s.atom(constant_positions[cid]),[s.atom(0)],[s.atom(0)],[s.atom(0)],[s.atom(1),s.atom(rid),s.atom(1)],s.atom(object_class+'.'+name,True),s.atom(0)]
    objects[cid]=[cm,copy.deepcopy(root[1]),[s.atom(0)]]
    if kind not in ('Constant','Catalog'):
        layout=json.loads(Path(__file__).with_name(kind.lower()+'_layout_851.json').read_text(encoding='utf-8'))
        if layout.get('inline_collections'):
            import inline_object_xml
            features=inline_object_xml.features(s.Parser(body.decode('utf-8-sig')).documents()[0],layout)
            cm[13]=[s.atom(len(features))]+[s.atom(v) for v in features]
        dependencies=[];native=s.Parser(body.decode('utf-8-sig')).documents()[0]
        for profile in layout.get('reference_values',{}).values():
            value=native
            for slot in profile['path']:value=value[slot]
            key=s.val(value)
            if key!=s.ZERO and key not in dependencies:dependencies.append(key)
        for profile in layout.get('reference_lists',{}).values():
            row=native
            for slot in profile['path']:row=row[slot]
            for item in row[2:]:
                value=item
                for slot in profile['id_path']:value=value[slot]
                key=s.val(value)
                if key not in dependencies:dependencies.append(key)
        if dependencies:cm[14]=[s.atom(len(dependencies)+1),s.atom(rid)]+[s.atom(v) for v in dependencies]+[s.atom(1)]+[s.atom(0) for v in dependencies]
    if kind=='Catalog':
        from catalog_object_xml import inline_features
        inline=inline_features(s.Parser(body.decode('utf-8-sig')).documents()[0])
        cm[13]=[s.atom(len(inline))]+[s.atom(value) for value in inline]
        if new_forms:
            cls=identifiers.class_id('CatalogForm');cm[12]=[s.atom(1),[s.atom(cls),s.atom(len(new_forms))]+[s.atom(fid) for fid,_,_,_ in new_forms]]
            # The collection order in the Catalog XML defines form positions.
            positions={s.val(value):i for i,value in enumerate(s.Parser(body.decode('utf-8-sig')).documents()[0][7][2:])}
            for fid,fname,form_body,external in new_forms:
                versions[fid]=packets.content_version(form_body);originals[fid]=versions[fid];raws[fid]=form_body
                external_version=packets.external_version();version64=base64.b64encode(external_version).decode();form64=base64.b64encode(versions[fid]).decode();external_name=fid+'.0'
                fm=[s.atom(6),s.atom(fid),s.atom(cls),s.atom(cid),s.atom(s.ZERO),s.atom(4294967295),s.atom(0),s.atom(form64),s.atom(form64),s.atom(fname,True),s.atom(positions[fid]),
                    [s.atom(1),s.atom(external_name,True),s.atom(version64)],[s.atom(0)],[s.atom(0)],[s.atom(1),s.atom(cid),s.atom(1)],s.atom(s.val(cm[15])+cls+'.'+fname,True),s.atom(0)]
                objects[fid]=[fm,copy.deepcopy(root[1]),[s.atom(1),[s.atom(external_name,True),s.atom(version64),s.atom(0)]]]
                external_data[fid]=[(external_name,s.compress(external))];externals[fid]=[dict(name=external_name,version=external_version.hex(),action=0)]
    if kind=='CommonModule':
        from commonmodule_serializer import module_container
        external_name=cid+'.0';external_version=packets.external_version()
        external64=base64.b64encode(external_version).decode()
        cm[11]=[s.atom(1),s.atom(external_name,True),s.atom(external64)]
        objects[cid][2]=[s.atom(1),[s.atom(external_name,True),s.atom(external64),s.atom(1)]]
        external_data[cid]=[(external_name,s.compress(module_container(request['source_text']))) ]
        externals[cid]=[dict(name=external_name,version=external_version.hex(),action=1)]
    modules=request.get('modules',{})
    if not isinstance(modules,dict) or set(modules)-set(profiles.module_files(kind)):raise ValueError('Unsupported object module files')
    if modules:
        from commonmodule_serializer import module_container
        cm[11]=[s.atom(len(modules))];objects[cid][2]=[s.atom(len(modules))];external_data[cid]=[];externals[cid]=[]
        for filename,suffix in profiles.module_files(kind).items():
            if filename not in modules:continue
            stream=cid+suffix;version=packets.external_version();version64=base64.b64encode(version).decode()
            cm[11].extend([s.atom(stream,True),s.atom(version64)]);objects[cid][2].append([s.atom(stream,True),s.atom(version64),s.atom(1)])
            external_data[cid].append((stream,s.compress(module_container(modules[filename]))));externals[cid].append(dict(name=stream,version=version.hex(),action=1))
    import inline_command_xml as commands
    layout=json.loads(Path(__file__).with_name(kind.lower()+'_layout_851.json').read_text(encoding='utf-8')) if kind in profiles.profiles() else {}
    owned=commands.streams(s.Parser(body.decode('utf-8-sig')).documents()[0],layout)
    inline_modules=commands.module_inputs(request.get('inline_modules',{}),owned)
    if inline_modules:
        from commonmodule_serializer import module_container
        external_data.setdefault(cid,[]);externals.setdefault(cid,[])
        for owner,text in inline_modules.items():
            stream=owned[owner];version=packets.external_version();version64=base64.b64encode(version).decode()
            cm[11].extend([s.atom(stream,True),s.atom(version64)]);cm[11][0]=s.atom((len(cm[11])-1)//2)
            objects[cid][2].append([s.atom(stream,True),s.atom(version64),s.atom(1)]);objects[cid][2][0]=s.atom(len(objects[cid][2])-1)
            external_data[cid].append((stream,s.compress(module_container(text))));externals[cid].append(dict(name=stream,version=version.hex(),action=1))
        inline_streams.extend(dict(object_id=cid,name=stream) for stream in owned.values())
    nested=set(existing_order)-{oid for oid,_ in oldchildren}
    import related_object_changes
    changed_existing=related_object_changes.apply(request,objects,raws,versions,cid,kind)
    order=[fid for fid,_,_,_ in new_forms]+[cid,rid]+[oid for oid,_ in oldchildren]+sorted(nested)
    for oid in order:
        packets.commit_metadata(objects[oid][0],originals[oid],versions[oid])
    graph=packets.subtree_creation_graph(objects,rid,[cid]+[fid for fid,_,_,_ in new_forms],order,children,changed_existing) if new_forms or nested or changed_existing else packets.top_level_creation_graph(objects,rid,cid,order,children)
    payload=packets.assemble(graph,[packets.ObjectRecord(oid,s.text_bytes(objects[oid]),s.compress(raws[oid]),
        tuple(external_data.get(oid,()))) for oid in order])
    version_code=s.val(s.configuration_properties(docs,request['platform'])[15])
    features={rid:[identifiers.feature_id('ConstantCollectionChanged')]} if kind=='Constant' else {rid:[],cid:[]}
    xml=packets.request_xml(request,payload,{oid:objects[oid] for oid in order},originals,versions,externals,version_code,features)
    descriptions=[packets.description(objects[oid][0],originals[oid],versions[oid]) for oid in order]
    result=dict(request_xml=xml,object_id=cid,name=name,
                descriptions=descriptions,data=base64.b64encode(payload).decode(),
                version_code=s.val(s.configuration_properties(docs, request['platform'])[15]),existing_objects=sorted(expected),
                externals=[dict(object_id=oid,**item) for oid,items in externals.items() for item in items])
    if inline_streams:result['inline_streams']=inline_streams
    return result

def main():
    from serializer_cli import run
    run(lambda request: {'children':inspect(request)} if request.get('mode')=='inspect' else serialize(request))

if __name__=='__main__':main()
