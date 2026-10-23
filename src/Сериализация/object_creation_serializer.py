"""Creation packets for supported metadata objects and their managed forms."""
import configuration_xml
import base64
import copy
import json
import re
import uuid
import native_metadata as s
import packet_builder as packets
import metadata_identifiers as identifiers
import platform_profiles as platforms
import object_xml_profiles as profiles
import object_graph
from metadata_context import children, context_objects, guid
import metadata_object_xml
import serialization_context
from native_content import ObjectContent, CreationContent


CLASS = identifiers.class_id('Constant')


LANGUAGE = identifiers.class_id('Language')


def inspect(request):
    objects = context_objects(request['context'])
    oid = guid(request['object_id'])
    m = objects[oid][0]
    if s.val(m[2]) != configuration_xml.ROOT_CLASS or s.val(m[3]) != s.ZERO:
        raise ValueError('Configuration root required')
    return [child for child in object_graph.closure(objects,oid,children) if child!=oid]


def serialize(request,*,reference_objects=None,batch_relations=False,contents_only=False,definition=None):
    kind = request["object_type"]
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
    import managed_form_profiles as form_profiles
    if not isinstance(form_inputs,list) or len(form_inputs)>256 or (form_inputs and kind not in form_profiles.owner_profiles()):raise ValueError('Invalid creation forms')
    for entry in form_inputs:
        if not isinstance(entry,dict) or set(entry)!={'name','definition_xml','form_xml','module_text'}:raise ValueError('Invalid creation form files')
        import form_definition_xml
        fid,fname,_=form_definition_xml.read(entry['definition_xml'],kind,request['platform'])
        if fname!=entry['name'] or fname.casefold() in {n.casefold() for n in form_names} or fid in form_names.values():raise ValueError('Duplicate or mismatched creation form')
        if not isinstance(entry['form_xml'],str):raise ValueError('Creation form requires complete Form.xml')
        form_names[fname]=fid
    if sum(len(json.dumps(entry).encode('utf-8')) for entry in form_inputs)>s.MAX_BYTES:raise ValueError('Oversized creation forms')
    template_inputs=request.get('templates',[]);template_names={};new_templates=[]
    if not isinstance(template_inputs,list) or len(template_inputs)>256 or sum(len(json.dumps(entry).encode('utf-8')) for entry in template_inputs)>s.MAX_BYTES:raise ValueError('Invalid or oversized creation templates')
    for entry in template_inputs:
        if not isinstance(entry,dict) or set(entry) not in ({'name','definition_xml','template_xml'},{'name','definition_xml','template_data'}):raise ValueError('Invalid creation template files')
        import template_serializer,template_content
        if not platforms.legacy(request['platform']):raise ValueError('Templates require the legacy platform profile')
        if template_serializer.metadata_kind(entry['definition_xml'])!='Template':raise ValueError('Expected an owned Template definition')
        tid,tname,template_body=template_serializer.native_definition(entry['definition_xml'],request['platform'])
        if tname!=entry['name'] or tname.casefold() in {name.casefold() for name in template_names} or tid in list(template_names.values())+list(form_names.values()):raise ValueError('Duplicate or mismatched creation Template')
        template_names[tname]=tid
        new_templates.append((tid,tname,template_body,entry))
    import native_references,metadata_targets,inline_object_xml,metadata_type_references
    allocation=None
    if '_native_references' not in request:
        allocation=metadata_object_xml.allocate_creation(request['object_xml'],request['platform'],kind)
        if isinstance(definition,metadata_object_xml.PreparedCreation):
            allocation=metadata_object_xml.TypeAllocation(allocation.platform,allocation.kind,allocation.object_id,allocation.name,tuple(definition.result[3][:len(allocation.generated)]))
        targets=metadata_targets.creation(kind,allocation.object_id,allocation.name,form_names,objects,rid,template_names)
        reader=native_references.Catalog(request,targets)
        reader.declare(allocation);request=dict(request,_native_references=reader)
    else:
        reader=native_references.catalog(request)
    type_references=metadata_type_references.resolve(request['object_xml'],request)
    import xdto_packages,xdto_type_xml
    xdto_types=xdto_packages.for_web(request['object_xml'],request,reference_objects if reference_objects is not None else objects)
    package_dependencies=set()
    if kind=='XDTOPackage':_,package_dependencies,_=xdto_packages.for_package(request,request['object_xml'],request.get('file_data',{}))
    if definition is None:
        if allocation is None:
            from xml.etree import ElementTree as E
            allocation=reader.allocations.get(E.fromstring(request['object_xml'])[0].get('uuid'))
        cid,name,body,generated=metadata_object_xml.create(request['object_xml'],request['platform'],kind,form_names,objects,rid,reference_objects,template_names,type_references=type_references,allocation=allocation,xdto_types=xdto_types)
    else:
        if (not isinstance(definition,metadata_object_xml.PreparedCreation)
                or (definition.source,definition.platform,definition.kind,definition.forms,definition.templates,definition.types,definition.xdto)!=(request['object_xml'],request['platform'],kind,tuple(sorted(form_names.items())),tuple(sorted(template_names.items())),tuple(sorted(type_references.items())),xdto_type_xml.freeze(xdto_types))):
            raise ValueError('Prepared creation definition differs from XML, platform or child identities')
        cid,name,body,generated=definition.result
    generated=list(generated)
    if cid in objects or any(s.val(objects[oid][0][9]).casefold()==name.casefold() for oid,cls in oldchildren if cls==object_class):
        raise ValueError(f'{kind} UUID or name already exists')
    features=inline_object_xml.features(s.Parser(body.decode('utf-8-sig')).documents()[0],profiles.layout(kind,request['platform'])) if kind in profiles.change_types() else []
    if definition is None or cid not in reader.compiled:reader.register(cid,body,features)
    if new_templates:
        new_templates=[(tid,tname,raw,template_content.convert(dict(request,**entry))) for tid,tname,raw,entry in new_templates]
    if form_inputs:
        import managed_form_operations,metadata_references
        owner=s.Parser(body.decode('utf-8-sig')).documents()[0]
        for entry in form_inputs:
            references=metadata_references.resolve(entry['form_xml'],request)
            fid,form_body,external=managed_form_operations.create_native(kind,entry['name'],request['platform'],owner,entry['definition_xml'],entry['form_xml'],entry['module_text'],references,rid if kind=='Report' else None)
            new_forms.append((fid,entry['name'],form_body,external))
    generated+=list(form_names.values())+list(template_names.values())
    if len(set(generated+[cid]))!=len(generated)+1:raise ValueError('Duplicate '+kind+', inline or stored child UUID')
    known=set(objects)
    if any(g in known for g in generated):raise ValueError('Generated type UUID collides with an object')
    raws={};versions={};originals={};externals={};external_data={};inline_streams=[]
    for oid in sorted(expected):
        data=base64.b64decode(request['snapshots'][oid],validate=True);s.validate_storage(data)
        meta,pos=s.read_record(data,12);content,pos=s.read_record(data,pos)
        saved=s.Parser(meta.decode('utf-8-sig')).documents()[0];m=objects[oid][0]
        serialization_context.validate_metadata(saved,m,oid)
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
        # Owner module streams do not require decoding an unchanged opaque body.
        # Only inline-owned streams need their owner identities from the profile.
        if any(not s.val(refs[index]).startswith(oid+'.') for index in range(1,len(refs),2)):
            object_kind=identifiers.class_labels().get(s.val(m[2]))
            if object_kind in profiles.profiles():
                import inline_command_xml as commands
                layout=profiles.layout(object_kind)
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
    if kind in profiles.change_types():
        layout=profiles.layout(kind,request['platform'])
        import inline_object_xml
        native=s.Parser(body.decode('utf-8-sig')).documents()[0]
        features=inline_object_xml.features(native,layout)
        cm[13]=[s.atom(len(features))]+[s.atom(v) for v in features]
        dependencies={rid:1}
        dependencies.update((key,0) for key in package_dependencies)
        dependencies.update(metadata_object_xml.reference_dependencies(native,layout,cid))
        cm[14]=[s.atom(len(dependencies))]+[s.atom(key) for key in dependencies]+[s.atom(value) for value in dependencies.values()]
    dependencies=s.metadata_relations(cm[14])
    for key in metadata_type_references.object_ids(request['object_xml'],reader):
        if key!=cid:dependencies.setdefault(key,0)
    cm[14]=[s.atom(len(dependencies))]+[s.atom(key) for key in dependencies]+[s.atom(value) for value in dependencies.values()]
    new_children=[(row,identifiers.class_id(form_profiles.form_kind(kind))) for row in new_forms]+[(row,identifiers.class_id('Template')) for row in new_templates]
    if new_children:
        groups={};positions={}
        for row,cls in new_children:
            groups.setdefault(cls,[]).append(row[0])
        import native_collection_editor as collections
        owner=s.Parser(body.decode('utf-8-sig')).documents()[0]
        for cls,keys in groups.items():
            ordered=[s.val(key) for key in collections.creation_row(owner,cls)[2:]]
            if set(ordered)!=set(keys):raise ValueError('Creation child files differ from native owner collection')
            groups[cls]=ordered;positions.update({key:index for index,key in enumerate(ordered)})
        cm[12]=[s.atom(len(groups))]+[[s.atom(cls),s.atom(len(keys))]+[s.atom(key) for key in keys] for cls,keys in groups.items()]
        for (fid,fname,form_body,external),cls in new_children:
            versions[fid]=packets.content_version(form_body);originals[fid]=versions[fid];raws[fid]=form_body
            external_version=packets.external_version();version64=base64.b64encode(external_version).decode();form64=base64.b64encode(versions[fid]).decode();external_name=fid+'.0'
            fm=[s.atom(6),s.atom(fid),s.atom(cls),s.atom(cid),s.atom(s.ZERO),s.atom(4294967295),s.atom(0),s.atom(form64),s.atom(form64),s.atom(fname,True),s.atom(positions[fid]),
                [s.atom(1),s.atom(external_name,True),s.atom(version64)],[s.atom(0)],[s.atom(0)],[s.atom(1),s.atom(cid),s.atom(1)],s.atom(s.val(cm[15])+cls+'.'+fname,True),s.atom(0)]
            objects[fid]=[fm,copy.deepcopy(root[1]),[s.atom(1),[s.atom(external_name,True),s.atom(version64),s.atom(0)]]]
            external_data[fid]=[(external_name,s.compress(external))];externals[fid]=[dict(name=external_name,version=external_version.hex(),action=0)]
    if kind=='CommonModule':
        if request.get('clear_module_text') and request.get('source_text')!='':raise ValueError('Cleared CommonModule must have empty source text')
    if kind=='CommonModule' and not request.get('clear_module_text'):
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
    import object_file_content
    files=object_file_content.convert(kind,request['object_xml'],request.get('file_data',{}),request)
    object_file_content.apply_relations(cm,files)
    if files:
        external_data.setdefault(cid,[]);externals.setdefault(cid,[])
        for filename,content in files.items():
            raw=content.data
            stream=cid+profiles.content_files(kind)[filename]['suffix'];version=packets.external_version();version64=base64.b64encode(version).decode()
            cm[11].extend([s.atom(stream,True),s.atom(version64)]);cm[11][0]=s.atom((len(cm[11])-1)//2)
            objects[cid][2].append([s.atom(stream,True),s.atom(version64),s.atom(1)]);objects[cid][2][0]=s.atom(len(objects[cid][2])-1)
            external_data[cid].append((stream,s.compress(raw)));externals[cid].append(dict(name=stream,version=version.hex(),action=1))
    import inline_command_xml as commands
    layout=profiles.layout(kind) if kind in profiles.profiles() else {}
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
    changed_existing=[] if batch_relations else related_object_changes.apply(request,objects,raws,versions,cid,kind)
    order=[row[0] for row,cls in new_children]+[cid,rid]+[oid for oid,_ in oldchildren]+sorted(nested)
    for oid in order:
        packets.commit_metadata(objects[oid][0],originals[oid],versions[oid])
    version_code=s.val(configuration_xml.configuration_properties(docs,request['platform'])[15])
    if contents_only:
        return CreationContent({key:ObjectContent(objects[key],raws[key],list(external_data.get(key,())),externals.get(key,[]))
                                for key in [row[0] for row,cls in new_children]+[cid]},version_code)
    graph=packets.subtree_creation_graph(objects,rid,[cid]+[row[0] for row,cls in new_children],order,children,changed_existing) if new_children or nested or changed_existing else packets.top_level_creation_graph(objects,rid,cid,order,children)
    payload=packets.assemble(graph,[packets.ObjectRecord(oid,s.text_bytes(objects[oid]),s.compress(raws[oid]),
        tuple(external_data.get(oid,()))) for oid in order])
    features={rid:[identifiers.feature_id('ConstantCollectionChanged')]} if kind=='Constant' and not platforms.legacy(request['platform']) else {rid:[],cid:[]}
    xml=packets.request_xml(request,payload,{oid:objects[oid] for oid in order},originals,versions,externals,version_code,features)
    descriptions=[packets.description(objects[oid][0],originals[oid],versions[oid]) for oid in order]
    result=dict(request_xml=xml,object_id=cid,name=name,
                descriptions=descriptions,data=base64.b64encode(payload).decode(),
                version_code=s.val(configuration_xml.configuration_properties(docs, request['platform'])[15]),existing_objects=sorted(expected),
                externals=[dict(object_id=oid,**item) for oid,items in externals.items() for item in items])
    if inline_streams:result['inline_streams']=inline_streams
    return result


def main():
    from serializer_cli import run
    run(lambda request: {'children':inspect(request)} if request.get('mode')=='inspect' else serialize(request))


if __name__=="__main__":main()
