"""Whole-XML replacement of an existing object using verified object profiles."""
import metadata_context
import xml_namespaces
import base64
import copy
import uuid
from xml.etree import ElementTree as E
import native_metadata as s
from native_content import ObjectContent
import metadata_identifiers as ids
import serialization_context as contexts
import metadata_object_xml as flat
import object_xml_profiles as profiles
import inline_object_xml as inline
import packet_builder as packets
from commonmodule_serializer import module_container


def at(node,path):
    for slot in path:node=node[slot]
    return node


def serialize(request,native_content=False,*,reference_objects=None):
    kind=request['object_type']
    if kind not in profiles.change_types():
        import metadata_owner_change
        return metadata_owner_change.serialize(request,native_content,reference_objects=reference_objects)
    if kind=='CommonModule':
        raise ValueError('Use the dedicated converter for this metadata class')
    text=request.get('object_xml')
    if not isinstance(text,str) or len(text.encode('utf-8'))>s.MAX_BYTES or '<!DOCTYPE' in text.upper():raise ValueError('Complete object XML is required')
    root=E.fromstring(text)
    if root.tag!='{'+xml_namespaces.MD+'}MetaDataObject' or len(root)!=1 or root[0].tag!='{'+xml_namespaces.MD+'}'+profiles.xml_kind(kind):raise ValueError('Unexpected object XML class')
    oid=metadata_context.guid(request['object_id']);frame=contexts.read(request,oid);m=frame.metadata
    if s.val(m[2])!=ids.class_id(kind) or s.val(m[3])==s.ZERO or s.val(m[4])!=s.ZERO:
        raise ValueError('Unsupported object metadata or separately stored children')
    # getObjects may omit the child map; the native body and updateInfo still
    # have to agree through child_object_xml.validate below.
    if s.render(frame.saved[0][12])!='{0}' and sorted(metadata_context.children(m))!=sorted(metadata_context.children(frame.saved[0])):
        raise ValueError('Snapshot/context maps differ: 12')
    if ({s.val(key) for key in m[13][1:]}!={s.val(key) for key in frame.saved[0][13][1:]}
            or s.val(m[13][0])!=s.val(frame.saved[0][13][0])
            or s.metadata_relations(m[14])!=s.metadata_relations(frame.saved[0][14])):
        raise ValueError('Snapshot/context features or relations differ')
    original=contexts.original_version(request['original_version'],m)
    objects=metadata_context.context_objects(request['context'])
    import native_collection_editor as collections
    import metadata_structure
    editing='_removed_children' in request or (kind in metadata_structure.automatic_owners() and bool(collections.rules(kind)))
    if editing:
        import automatic_deletion
        xml_children=E.fromstring(request['object_xml'])[0].find('{'+xml_namespaces.MD+'}ChildObjects')
        missing=automatic_deletion.missing(request['object_xml'],oid,objects,reference_objects=reference_objects) if metadata_context.children(m) or xml_children is not None else []
        expected_removed=[key for key in request.get('_removed_children',[]) if key in objects and s.val(objects[key][0][3])==oid]
        if set(missing)!=set(expected_removed):raise ValueError('Existing child references and order must be preserved unless explicitly removed')
    source_docs=s.Parser(s.inflate(frame.data).decode('utf-8-sig')).documents()
    if len(source_docs)!=1:raise ValueError('Unsupported object body documents')
    source=source_docs[0]
    layout=profiles.layout(kind)
    removed=request.get('_removed_children',[])
    pairs=metadata_context.children(m)
    for child,cls in pairs:
        if child not in objects or s.val(objects[child][0][2])!=cls or s.val(objects[child][0][3])!=oid:
            raise ValueError('Invalid stored child context')
    import metadata_type_references
    type_references=metadata_type_references.resolve(request['object_xml'],request)
    import xdto_packages
    xdto_types=xdto_packages.for_web(request['object_xml'],request,reference_objects if reference_objects is not None else objects)
    package_dependencies=set();managed_imports=set()
    if kind=='XDTOPackage':_,package_dependencies,managed_imports=xdto_packages.for_package(request,request['object_xml'],request.get('file_data',{}))
    raw,new_features=flat.change(request['object_xml'],request['platform'],kind,source,removed=removed,objects=objects,metadata=m,reference_objects=reference_objects,type_references=type_references,xdto_types=xdto_types,allow_rename=request.get('_allow_rename',False))
    target=s.Parser(raw.decode('utf-8-sig')).documents()[0]
    m[9]=copy.deepcopy(flat.at(target,flat.common_path(layout))[2])
    old_features=inline.features(source,layout)
    if set(new_features)&set(objects):raise ValueError('Inline UUID collides with a repository object')
    if (int(s.val(m[13][0]))!=len(old_features) or len(m[13])!=len(old_features)+1
            or {s.val(key) for key in m[13][1:]}!=set(old_features)):
        raise ValueError('Source inline feature map differs from body')
    m[13]=[s.atom(len(new_features))]+[s.atom(key) for key in new_features]
    relations=s.metadata_relations(m[14])
    for key in removed:relations.pop(key,None)
    relations.update({child:1 for child,cls in pairs if child not in removed})
    if relations.get(s.val(m[3]))!=1:raise ValueError('Missing parent relation')
    relations=metadata_type_references.reconcile(request,source,target,layout,relations,oid,request['object_xml'])
    for key in managed_imports-package_dependencies:
        if relations.get(key)==0:relations.pop(key)
    for key in package_dependencies:relations.setdefault(key,0)
    relations.update(flat.reference_dependencies(target,layout,oid))
    m[14]=[s.atom(len(relations))]+[s.atom(key) for key in relations]+[s.atom(flag) for flag in relations.values()]
    import inline_command_xml as commands
    owned_streams=commands.streams(target,layout);old_owned_streams=commands.streams(source,layout)
    removed_streams=set(old_owned_streams.values())-set(owned_streams.values())
    modules=request.get('modules',{});module_files=profiles.module_files(kind)
    if not isinstance(modules,dict) or set(modules)-set(module_files):raise ValueError('Unsupported object module files')
    inline_modules=commands.module_inputs(request.get('inline_modules',{}),owned_streams)
    for key,allowed,supplied in (('removed_modules',module_files,modules),('removed_inline_modules',owned_streams,inline_modules)):
        names_to_remove=request.get(key,[])
        if (not isinstance(names_to_remove,list) or any(not isinstance(name,str) for name in names_to_remove)
                or len(set(names_to_remove))!=len(names_to_remove) or set(names_to_remove)-set(allowed) or set(names_to_remove)&set(supplied)):
            raise ValueError('Invalid module removals: '+key)
        removed_streams.update(oid+module_files[name] if key=='removed_modules' else owned_streams[name] for name in names_to_remove)
    refs=m[11];count=int(s.val(refs[0]));streams={};external_docs=frame.docs[2]
    if len(refs)!=1+count*2 or (s.render(external_docs)!='{0}' and (len(external_docs)!=count+1 or int(s.val(external_docs[0]))!=count)):
        raise ValueError('Invalid source external map')
    seen_streams=set()
    for index in range(count):
        stream=s.val(refs[1+index*2]);version=s.val(refs[2+index*2])
        if stream in seen_streams or (not stream.startswith(oid+'.') and stream not in old_owned_streams.values()):
            raise ValueError('Source external maps differ')
        seen_streams.add(stream)
        if s.render(external_docs)!='{0}':
            entry=external_docs[index+1]
            if len(entry)!=3 or s.val(entry[0])!=stream or s.val(entry[1])!=version or s.val(entry[2])!='1':raise ValueError('Source external maps differ')
        source_version=uuid.UUID(version).bytes_le+bytes(4)
        if stream not in removed_streams:streams[stream]=(source_version,0)
    payloads=[]
    import object_file_content
    files=object_file_content.convert(kind,request['object_xml'],request.get('file_data',{}),request)
    object_file_content.apply_relations(m,files)
    for filename,content in files.items():
        payload=content.data
        stream=oid+profiles.content_files(kind)[filename]['suffix'];version=packets.external_version()
        streams[stream]=(version,1);payloads.append((stream,s.compress(payload)))
    for module,text in modules.items():
        stream=oid+module_files[module];version=packets.external_version()
        streams[stream]=(version,1);payloads.append((stream,s.compress(module_container(text))))
    for owner,text in inline_modules.items():
        stream=owned_streams[owner];version=packets.external_version();streams[stream]=(version,1);payloads.append((stream,s.compress(module_container(text))))
    m[11]=[s.atom(len(streams))];frame.docs[2]=[s.atom(len(payloads))];externals=[]
    for stream,(version,action) in streams.items():
        version64=base64.b64encode(version).decode()
        m[11].extend([s.atom(stream,True),s.atom(version64)])
        if action:frame.docs[2].append([s.atom(stream,True),s.atom(version64),s.atom(action)])
        externals.append(dict(name=stream,version=version.hex(),action=action))
    raw=s.native_body_bytes([target])
    if native_content:return ObjectContent(frame.docs,raw,payloads,externals)
    import external_dependencies
    lost=set(old_features)-set(new_features)
    external_dependencies.validate(request,objects,(),lost,{oid:(frame.docs,raw,payloads)})
    version=packets.content_version(raw);source_version=bytes.fromhex(original)
    packets.commit_metadata(m,source_version,version)
    m[15:17]=copy.deepcopy(frame.saved[0][15:17]);frame.docs[1]=copy.deepcopy(frame.saved[1])
    graph=packets.change_graph(m,packets.child_map(pairs),externals=m[11])
    payload=packets.assemble(graph,[packets.ObjectRecord(oid,s.text_bytes(frame.docs),s.compress(raw),tuple(payloads))])
    return dict(request_xml=packets.request_xml(request,payload,{oid:frame.docs},{oid:source_version},{oid:version},{oid:externals}),external_owners=list(owned_streams))


def main():
    from serializer_cli import run
    run(serialize)


if __name__=='__main__':main()
