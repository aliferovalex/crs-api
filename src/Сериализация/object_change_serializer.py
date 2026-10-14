"""Whole-XML replacement of an existing object using verified object profiles."""
import base64
import copy
import json
import uuid
from pathlib import Path
from xml.etree import ElementTree as E
import metadata_serializer as s
import metadata_identifiers as ids
import serialization_context as contexts
import flat_object_serializer as flat
import object_xml_profiles as profiles
import inline_object_xml as inline
import constant_serializer as c
import packet_builder as packets
from commonmodule_serializer import module_container


def at(node,path):
    for slot in path:node=node[slot]
    return node


def replace(node,path,value):
    at(node,path[:-1])[path[-1]]=copy.deepcopy(value)


def serialize(request):
    kind=request['object_type']
    if kind not in profiles.profiles() or kind in ('Catalog','CommonModule'):
        raise ValueError('Use the dedicated converter for this metadata class')
    oid=c.guid(request['object_id']);frame=contexts.read(request,oid);m=frame.metadata
    if s.val(m[2])!=ids.class_id(kind) or s.val(m[3])==s.ZERO or s.val(m[4])!=s.ZERO:
        raise ValueError('Unsupported object metadata or separately stored children')
    if s.render(m[11])!=s.render(frame.saved[0][11]):raise ValueError('Snapshot/context maps differ: 11')
    # getObjects may omit the child map; the native body and updateInfo still
    # have to agree through child_object_xml.validate below.
    if s.render(frame.saved[0][12])!='{0}' and sorted(c.children(m))!=sorted(c.children(frame.saved[0])):
        raise ValueError('Snapshot/context maps differ: 12')
    if ({s.val(key) for key in m[13][1:]}!={s.val(key) for key in frame.saved[0][13][1:]}
            or s.val(m[13][0])!=s.val(frame.saved[0][13][0])
            or s.metadata_relations(m[14])!=s.metadata_relations(frame.saved[0][14])):
        raise ValueError('Snapshot/context features or relations differ')
    original=contexts.original_version(request['original_version'],m)
    objects=c.context_objects(request['context'])
    actual,name,raw,_=flat.object_xml(request['object_xml'],request['platform'],kind,objects)
    if actual!=oid or name!=s.val(m[9]):raise ValueError('Object XML identity differs from repository')
    source_docs=s.Parser(s.inflate(frame.data).decode('utf-8-sig')).documents()
    target_docs=s.Parser(raw.decode('utf-8-sig')).documents()
    if len(source_docs)!=1 or len(target_docs)!=1:raise ValueError('Unsupported object body documents')
    source=source_docs[0];target=target_docs[0]
    layout=json.loads(Path(__file__).with_name(kind.lower()+'_layout_851.json').read_text(encoding='utf-8'))
    import child_object_xml as child_xml
    pairs=child_xml.validate(source,target,layout,m,objects)
    import catalog_tabular_xml as tabular
    for profile in layout.get('tabular_collections',{}).values():
        old={s.val(tabular.common(entry)[1][2]):entry for entry in source[profile['slot']][2:]}
        for entry in target[profile['slot']][2:]:
            previous=old.get(s.val(tabular.common(entry)[1][2]))
            if previous is not None and s.render(entry[0][1][1:5])!=s.render(previous[0][1][1:5]):
                raise ValueError('Existing TabularSection generated UUIDs must remain unchanged')
    common_path=layout.get('common_path',[1,layout.get('common_slot',9)]+([] if layout.get('common_direct') else [1]))
    if E.fromstring(request['object_xml'])[0].find('{'+c.MD+'}InternalInfo') is None:
        for slot in layout['generated_slots']:target[1][slot]=copy.deepcopy(source[1][slot])
    baseline=copy.deepcopy(target)
    for slot in (3,4):replace(baseline,common_path+[slot],at(source,common_path+[slot]))
    mutable=list(layout.get('string_slots',{}).values())
    mutable.extend(profile['path'] for profile in layout.get('scalar_properties',{}).values())
    mutable.extend(layout.get('localized_properties',{}).values())
    if 'type_path' in layout:mutable.append(layout['type_path'])
    for category in ('reference_lists','reference_values'):
        mutable.extend(profile['path'] for profile in layout.get(category,{}).values())
    mutable.extend([profile['slot']] for profile in layout.get('inline_collections',{}).values())
    mutable.extend([profile['slot']] for profile in layout.get('tabular_collections',{}).values())
    mutable.extend([profile['slot']] for profile in layout.get('command_collections',{}).values())
    if 'values_slot' in layout:mutable.append([layout['values_slot']])
    for path in mutable:replace(baseline,path,at(source,path))
    if s.render(baseline)!=s.render(source):
        raise ValueError('Source body or generated identifiers are outside the verified whole-object profile')
    old_features=inline.features(source,layout);new_features=inline.features(target,layout)
    old_scopes,new_scopes=inline.scopes(source,layout),inline.scopes(target,layout)
    if any(old_scopes[key]!=new_scopes[key] for key in set(old_scopes)&set(new_scopes)):
        raise ValueError('Existing inline UUID cannot move between collections')
    if set(new_features)&set(objects):raise ValueError('Inline UUID collides with a repository object')
    if (int(s.val(m[13][0]))!=len(old_features) or len(m[13])!=len(old_features)+1
            or {s.val(key) for key in m[13][1:]}!=set(old_features)):
        raise ValueError('Source inline feature map differs from body')
    m[13]=[s.atom(len(new_features))]+[s.atom(key) for key in new_features]
    relations=s.metadata_relations(m[14])
    if relations.get(s.val(m[3]))!=1:raise ValueError('Missing parent relation')
    for profile in layout.get('reference_values',{}).values():
        key=s.val(at(target,profile['path']))
        if key!=s.ZERO:relations[key]=0
    for profile in layout.get('reference_lists',{}).values():
        for item in at(target,profile['path'])[2:]:relations[s.val(at(item,profile['id_path']))]=0
    m[14]=[s.atom(len(relations))]+[s.atom(key) for key in relations]+[s.atom(flag) for flag in relations.values()]
    import inline_command_xml as commands
    owned_streams=commands.streams(target,layout);old_owned_streams=commands.streams(source,layout)
    if set(old_owned_streams)-set(owned_streams):raise ValueError('Removing commands with module streams requires a deletion package')
    modules=request.get('modules',{});module_files=profiles.module_files(kind)
    if not isinstance(modules,dict) or set(modules)-set(module_files):raise ValueError('Unsupported object module files')
    refs=m[11];count=int(s.val(refs[0]));streams={};external_docs=frame.docs[2]
    if len(refs)!=1+count*2 or (s.render(external_docs)!='{0}' and (len(external_docs)!=count+1 or int(s.val(external_docs[0]))!=count)):
        raise ValueError('Invalid source external map')
    for index in range(count):
        stream=s.val(refs[1+index*2]);version=s.val(refs[2+index*2])
        if stream in streams or (not stream.startswith(oid+'.') and stream not in old_owned_streams.values()):
            raise ValueError('Source external maps differ')
        if s.render(external_docs)!='{0}':
            entry=external_docs[index+1]
            if len(entry)!=3 or s.val(entry[0])!=stream or s.val(entry[1])!=version or s.val(entry[2])!='1':raise ValueError('Source external maps differ')
        streams[stream]=(uuid.UUID(version).bytes_le+bytes(4),0)
    payloads=[]
    for module,text in modules.items():
        stream=oid+module_files[module];version=packets.external_version()
        streams[stream]=(version,1);payloads.append((stream,s.compress(module_container(text))))
    inline_modules=commands.module_inputs(request.get('inline_modules',{}),owned_streams)
    for owner,text in inline_modules.items():
        stream=owned_streams[owner];version=packets.external_version();streams[stream]=(version,1);payloads.append((stream,s.compress(module_container(text))))
    m[11]=[s.atom(len(streams))];frame.docs[2]=[s.atom(len(payloads))];externals=[]
    for stream,(version,action) in streams.items():
        version64=base64.b64encode(version).decode()
        m[11].extend([s.atom(stream,True),s.atom(version64)])
        if action:frame.docs[2].append([s.atom(stream,True),s.atom(version64),s.atom(action)])
        externals.append(dict(name=stream,version=version.hex(),action=action))
    raw=s.native_body_bytes([target]);version=packets.content_version(raw);source_version=bytes.fromhex(original)
    packets.commit_metadata(m,source_version,version)
    m[15:17]=copy.deepcopy(frame.saved[0][15:17]);frame.docs[1]=copy.deepcopy(frame.saved[1])
    graph=packets.change_graph(m,packets.child_map(pairs),externals=m[11])
    payload=packets.assemble(graph,[packets.ObjectRecord(oid,s.text_bytes(frame.docs),s.compress(raw),tuple(payloads))])
    return dict(request_xml=packets.request_xml(request,payload,{oid:frame.docs},{oid:source_version},{oid:version},{oid:externals}),external_owners=list(owned_streams))


def main():
    from serializer_cli import run
    run(serialize)


if __name__=='__main__':main()
