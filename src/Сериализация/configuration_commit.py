"""Compile complete export changes through ibcmd-rs, then build one CRS packet."""
import base64,copy,uuid,hashlib
from pathlib import Path
import metadata_context
import native_metadata as s
import packet_builder as packets
import serialization_context as contexts
import configuration_export as export
import export_xml as preparation
import compiled_metadata
import compiled_creation
import metadata_targets
import platform_profiles
import compiled_graph


def prepare(request):
    plan=export.plan(request)
    objects=metadata_context.context_objects(request['context'])
    baseline=export.inventory(request['baseline_directory'])[2]
    _,_,target,_=export.inventory(request['directory'])
    changes=[]
    for operation in plan['operations']:
        if operation['operation']=='Удаление':continue
        kind=operation['kind'];oid=operation['object_id']
        text=preparation.read(operation['xml_path'])
        row=dict(object_id=oid,kind=kind,object_xml=text)
        row['_new']=oid in plan['new_ids']
        row['_record']=target[oid]
        row['_position']=operation.get('position')
        row['_removed_children']={key:baseline[key] for key in plan['removed_ids'] if s.val(objects[key][0][3])==oid}
        row['_new_children']={key:target[key] for key in plan['new_ids'] if target[key]['parent_id']==oid}
        if kind.endswith('Form'):
            prefix=Path(operation['xml_path']).with_suffix('')
            row['form_xml']=preparation.read(prefix/'Ext/Form.xml')
        changes.append(row)
    # Compilation can rebuild a dependent record whose XML did not change.
    # Its source version must already be available before observing the CF delta.
    plan['snapshot_ids']=list(objects) if changes else list(plan['removed_ids'])
    # Reference/type checks and owner bindings use authoritative version storage.
    plan['needs_storage']=bool(changes)
    return plan,changes


def final_graph(objects,kept,changed,removed,new_ids=()):
    a=s.atom;order=list(kept);graph=[[a(0)] for _ in range(15)]
    graph[0]=[a(len(order))];graph[3]=[a(len(order))];graph[4]=[a(len(objects)+len(new_ids))]
    for oid in order:
        graph[0].extend([a(oid),packets.descriptor(kept[oid][0])]);graph[3].extend([a(oid),kept[oid][0][3]])
    for oid in objects:graph[4].extend([a(oid),a(int(oid not in removed))])
    for oid in new_ids:graph[4].extend([a(oid),a(1)])
    graph[1]=[a(len(changed))];graph[2]=[a(len(changed))]
    for index in (5,7,8,9):graph[index]=[a(len(changed))]
    for oid in changed:
        m=kept[oid][0];graph[1].append([a(oid)]+copy.deepcopy(m[13]));graph[2].append(s.graph_relations(oid,m[14]))
        graph[5].extend([a(oid),packets.child_map(metadata_context.children(m))]);graph[7].extend([a(oid),m[11]])
        for index in (8,9):graph[index].extend([a(oid),a(1)])
    if new_ids:
        graph[6]=[a(len(changed))]
        for oid in changed:
            descendants=[]
            def collect(key):
                if key in descendants:raise ValueError('Cyclic final creation tree')
                descendants.append(key)
                for child,_ in metadata_context.children(kept[key][0]):collect(child)
            collect(oid);row=[a(len(descendants))]
            for key in descendants:row.extend([a(key),packets.descriptor(kept[key][0])])
            graph[6].extend([a(oid),row])
    graph[10]=a(int(bool(removed)));graph[12]=a(0);graph[14]=[a(1),[a(0)]]
    if removed:graph[11]=[a(len(objects))]+[s.graph_relations(oid,d[0][14]) for oid,d in objects.items()]
    return graph

def serialize(request):
    from ibcmd_backend import Compiler
    # There is deliberately no fallback XML writer.
    with Compiler(request) as compiler:
        return compile_configuration(request,compiler)


def compile_configuration(request,compiler):
    if not platform_profiles.legacy(request['platform']):raise ValueError('Complete configuration commit requires legacy profile')
    plan,changes=prepare(request)
    if not changes:raise ValueError('Export has no changes to commit')
    if plan['target_fingerprint']!=request['target_fingerprint'] or plan['baseline_fingerprint']!=request['baseline_fingerprint']:
        raise ValueError('Export directories changed after planning')
    objects=metadata_context.context_objects(request['context']);changed={};externals=[];versions={}
    for oid in plan['snapshot_ids']:
        frame=contexts.read(dict(request,snapshot=request['snapshots'][oid]),oid)
        contexts.original_version(request['originals'][oid],frame.metadata)
    compiler.prepare(request,plan,changes,objects)
    changes[:]=[row for row in changes if row['_new'] or row['object_id'] in compiler.delta.objects
                or row['_position'] is not None and row['_position']!=int(s.val(objects[row['object_id']][0][10]))]
    import native_references
    inventory=export.inventory(request['directory'])[2]
    request=dict(request,_compiled_types=compiled_graph.TypeIndex(inventory,compiler.after,request['platform']),
                 _source_types=compiled_graph.TypeIndex(export.inventory(request['baseline_directory'])[2],compiler.before,request['platform']))
    planned={row['object_id'] for row in changes}
    positions=export.positions(inventory)
    for oid,delta in compiler.delta.objects.items():
        if delta.operation=='delete' or oid in planned:continue
        record=inventory[oid];kind=export.runtime_kind(record,inventory)
        row=dict(object_id=oid,kind=kind,object_xml=preparation.read(Path(request['directory'])/record['path']),
                 _new=False,_record=record,_position=positions.get(oid),_removed_children={},_new_children={})
        if kind.endswith('Form'):row['form_xml']=preparation.read((Path(request['directory'])/record['path']).with_suffix('')/'Ext/Form.xml')
        changes.append(row)
        plan['operations'].append(dict(operation='Изменение',object_id=oid,kind=kind,xml_path=str(Path(request['directory'])/record['path']),changed_files=[],implicit=True))
    if not changes:raise ValueError('Compiled configuration has no native or position changes')
    for row in changes:
        if not row['_new']:
            compiled_metadata.validate_xml(row,Path(request['baseline_directory']),Path(request['directory']),Path(inventory[row['object_id']]['path']))
    reader=native_references.Catalog(request,metadata_targets.final(objects,inventory,allow_rename=True))
    request=dict(request,_native_references=reader)
    root_id=next(oid for oid,docs in objects.items() if s.val(docs[0][3])==s.ZERO)
    compiled={}
    if plan['new_ids']:
        root_saved=contexts.read(dict(request,snapshot=request['snapshots'][root_id]),root_id).saved if root_id in request['snapshots'] else objects[root_id]
        known=set(objects)
        for oid,docs in objects.items():
            known.update(s.val(v) for v in docs[0][13][1:])
            known.update(compiled_metadata.guid_counts(s.Parser(compiler.before[oid].decode('utf-8-sig')).documents()))
        creation_objects=dict(objects)
        for row in sorted(changes,key=lambda item:item['_record']['path'].count('/')):
            if not row['_new']:continue
            oid=row['object_id'];entry=compiled_creation.allocate(request,row,creation_objects,compiler.after,root_saved,inventory)
            creation_objects[oid]=entry.docs
            identity=next(v for v in reader.targets.targets if v.object_id==oid)
            generated=list(compiled_graph.generated(row['_record']))
            declared=[oid]+list(native_references.feature_ids(entry.docs[0]))+generated
            identifiers=set(declared)
            if len(identifiers)!=len(declared):raise ValueError('Created object/type/feature UUIDs are not disjoint')
            if identifiers&known:raise ValueError('Created object/type/feature UUID collides with an existing identity')
            known.update(identifiers);compiled[oid]=entry;reader.register(oid,entry.body,native_references.feature_ids(entry.docs[0]))
    for row in changes:
        if not row['_new'] and not row['kind'].endswith('Form'):
            compiled[row['object_id']]=compiler.content(request,row,objects)
    for oid,entry in compiled.items():reader.register(oid,entry.body,native_references.feature_ids(entry.docs[0]))
    for row in changes:
        if row['_new']:compiled[row['object_id']]=compiled_creation.finalize(request,row,compiled[row['object_id']])
    for row in sorted(changes,key=lambda item:item['_new']):
        oid=row['object_id']
        docs,body,streams,ext=compiled[oid] if oid in compiled else compiler.content(request,row,objects)
        if row['_position'] is not None:docs[0][10]=s.atom(row['_position'])
        if not row['_new']:docs[0][12]=copy.deepcopy(objects[oid][0][12])
        for group in docs[0][12][1:]:
            children=[v for v in group[2:] if s.val(v) not in plan['removed_ids']]
            group[1:]=[s.atom(len(children))]+children
        for key,record in row['_new_children'].items():
            cls=compiled[key].docs[0][2];groups=docs[0][12]
            group=next((item for item in groups[1:] if s.val(item[0])==s.val(cls)),None)
            if group is None:group=[cls,s.atom(0)];groups.append(group);groups[0]=s.atom(len(groups)-1)
            group.append(s.atom(key));group[1]=s.atom(len(group)-2)
        if row['_new']:
            local=base64.b64decode(s.val(docs[0][8]),validate=True);original=local
        else:
            frame=contexts.read(dict(request,snapshot=request['snapshots'][oid]),oid)
            docs[0][15:17]=copy.deepcopy(frame.saved[0][15:17]);docs[1]=copy.deepcopy(frame.saved[1])
            original=bytes.fromhex(request['originals'][oid]);local=packets.content_version(body)
        old_name=s.val(docs[0][9]);new_name=row['_record']['name']
        if old_name!=new_name:
            descriptor=s.val(docs[0][15])
            if descriptor:
                if not descriptor.endswith(old_name):raise ValueError('Unrecognized source descriptor for renamed object: '+oid)
                docs[0][15]=s.atom(descriptor[:-len(old_name)]+new_name,True)
            docs[0][9]=s.atom(new_name,True)
        packets.commit_metadata(docs[0],original,local)
        changed[oid]=(docs,body,tuple(streams));versions[oid]=(original,local)
        externals.extend(dict(object_id=oid,**entry) for entry in ext)
    removed=set(plan['removed_ids']);targets=set(removed)
    for oid in removed:targets.update(s.val(key) for key in objects[oid][0][13][1:])
    for oid,(docs,_,_) in changed.items():
        if oid not in objects:continue
        targets.update({s.val(key) for key in objects[oid][0][13][1:]}-{s.val(key) for key in docs[0][13][1:]})
    kept={oid:copy.deepcopy(docs) for oid,docs in objects.items() if oid not in removed}
    for oid,(docs,_,_) in changed.items():kept[oid]=docs
    if plan['new_ids']:
        for row in changes:
            if not row['_new_children']:continue
            parent=row['object_id']
            groups=request['_compiled_types'].facts(parent).children
            rows=[]
            for cls,children in groups.items():
                if not children:continue
                rows.append([s.atom(cls),s.atom(len(children))]+[s.atom(child) for child in children])
                for position,child in enumerate(children):kept[child][0][10]=s.atom(position)
            kept[parent][0][12]=[s.atom(len(rows))]+rows
    def referenced(node):return any(referenced(child) for child in node) if isinstance(node,list) else s.val(node) in targets
    for oid,docs in kept.items():
        if targets & s.metadata_relations(docs[0][14]).keys():raise ValueError('Final configuration has incoming deletion references from '+oid)
        if oid in changed and referenced(s.Parser(changed[oid][1].decode('utf-8-sig')).documents()):raise ValueError('Deleted feature remains in final object body')
    import external_dependencies
    external_dependencies.validate(request,objects,removed,targets,changed)
    descriptions={};requested=[]
    for oid,docs in kept.items():
        if oid in versions:original,local=versions[oid]
        else:
            original=uuid.UUID(s.val(docs[0][7])).bytes_le+bytes(4);local=uuid.UUID(s.val(docs[0][8])).bytes_le+bytes(4)
            docs[0][7]=s.atom(base64.b64encode(original).decode());docs[0][8]=s.atom(base64.b64encode(local).decode());docs[0][5]=s.atom(4294967295);docs[0][6]=s.atom(0)
        descriptor=packets.description(docs[0],original,local);requested.append(descriptor)
        if oid in changed:descriptions[oid]=descriptor
    records=[packets.ObjectRecord(oid,s.text_bytes(docs),s.compress(body),streams) for oid,(docs,body,streams) in changed.items()]
    for oid in plan['removed_ids']:
        m=objects[oid][0];original=uuid.UUID(s.val(m[7])).bytes_le+bytes(4);local=uuid.UUID(s.val(m[8])).bytes_le+bytes(4)
        requested.append(packets.description(m,original,local))
    payload=packets.assemble(final_graph(objects,kept,list(changed),removed,plan['new_ids']),records)
    final_plan=export.plan(request)
    if final_plan['target_fingerprint']!=plan['target_fingerprint'] or final_plan['baseline_fingerprint']!=plan['baseline_fingerprint']:raise ValueError('Export changed during compilation')
    root_id=next(oid for oid,row in inventory.items() if row['kind']=='Configuration')
    # The compiler has verified the complete target XML. Version may be
    # intentionally empty; do not substitute an older history label for it.
    version_code=inventory[root_id]['node'].findtext(export.Q+'Properties/'+export.Q+'Version') or ''
    result=dict(data=base64.b64encode(payload).decode(),descriptions=[descriptions[oid] for oid in changed],requested=requested,removed_ids=plan['removed_ids'],
                changed_ids=[oid for oid in changed if oid in objects],new_ids=plan['new_ids'],version_code=version_code,version_code_resolved=True,externals=externals,repository=request['repository'],platform=request['platform'],repository_version=request['repository_version'])
    result['verification']=[dict(id=oid,body_sha256=hashlib.sha256(body).hexdigest(),
        streams=[dict(name=s.val(key),sha256=hashlib.sha256(compiler.after[s.val(key)]).hexdigest()) for key in docs[0][11][1::2]])
        for oid,(docs,body,_) in changed.items()]
    if request.get('baseline_update'):
        import repository_baseline
        result['baseline_update']=repository_baseline.register(request,changed,payload,removed)
    return result


def run(request):
    if request.get('mode')=='plan':return prepare(request)[0]
    return serialize(request)


if __name__=='__main__':
    from serializer_cli import run as cli
    cli(run)
