"""Prepare final existing-object bodies and removals from a complete export.

Every owner is converted once against the same source context. Dependency checks
run on the combined final metadata, before building the single commit graph.
"""
import metadata_context
import xml_namespaces
import base64,copy,uuid
from pathlib import Path
from xml.etree import ElementTree as E
import native_metadata as s
import object_creation_serializer as c
import metadata_identifiers as ids
import packet_builder as packets
import serialization_context as contexts
import configuration_export as export
import preparation_plan as preparation
import automatic_deletion as deletion
import platform_profiles
import native_collection_editor as collections
import object_xml_profiles as profiles
import metadata_structure as structure


def prepare(request):
    plan=export.plan(request)
    # Existing owners are converted without newly named children first. Their
    # collections are replaced with the complete final set after creation.
    _,_,target,_=export.inventory(request['directory'])
    import role_dependencies
    plan['dependent_role_ids']=role_dependencies.expand(plan,target,metadata_context.context_objects(request['context']),request['directory'],request['baseline_directory'])
    import xdto_packages,metadata_targets
    xdto_catalog=xdto_packages.from_export(request['directory'],target)
    request=dict(request,_xdto_catalog=xdto_catalog)
    final_index=metadata_targets.final(metadata_context.context_objects(request['context']),target,allow_rename=True)
    plan_context=dict(context=request['context'],platform=request['platform'],_xdto_catalog=xdto_catalog,_reference_objects=final_index)
    if any(operation['kind']=='Role' for operation in plan['operations']):
        import metadata_definitions
        plan_context['_metadata_definitions']=metadata_definitions.from_inventory(target)
    if any(operation['kind']=='XDTOPackage' for operation in plan['operations']):
        xdto_catalog.validate()
        old_namespaces=set()
        for file in (Path(request['baseline_directory'])/'XDTOPackages').glob('*.xml'):
            old_namespaces.add(E.parse(file).getroot()[0].findtext(preparation.Q+'Properties/'+preparation.Q+'Namespace'))
        for record in target.values():
            if record['kind']!='WebService':continue
            text=preparation.read(Path(request['directory'])/record['path']);available=xdto_catalog.web_types(text,final_index)
            for uri,name in xdto_packages.required(text):
                if (uri in xdto_catalog.namespaces or uri in old_namespaces) and name not in available.get(uri,()):raise ValueError('Final WebService references a missing XDTO type: '+uri+':'+name)
    new_ids=set(plan['new_ids']);changes=[];operations_by_path={op['xml_path']:op for op in plan['operations'] if 'xml_path' in op}
    for path in plan['xml_paths']:
        text=preparation.read(path);kind,oid,_=preparation.metadata(text)
        if new_ids:
            text=without_new_children(text,oid,target,new_ids)
            change=preparation.plan(dict(plan_context,xml_path=path),object_xml=text,complete_export=True)
        else:change=preparation.plan(dict(plan_context,xml_path=path),complete_export=True)
        operation=operations_by_path[path]
        changed_companions={entry for name,entry in export.module_companions(target[change['object_id']],target).items() if name in operation['changed_files']}
        change['modules']={name:text for name,text in change.get('modules',{}).items() if ('modules',name) in changed_companions}
        change['inline_modules']=[entry for entry in change.get('inline_modules',[]) if ('inline_modules',entry['object_id']) in changed_companions]
        if change['kind'].endswith('Form'):
            change['interface_unchanged']=not any(name.endswith('/Ext/Form.xml') for name in operation['changed_files'])
        if change['kind']=='CommonModule' or change['kind'].endswith('Form') or change['kind'] in ('Template','CommonTemplate'):
            change['content_unchanged']=all(name==target[change['object_id']]['path'] for name in operation['changed_files'])
        for key in ('removed_modules','removed_inline_modules','clear_module_text'):
            if key in operation:change[key]=operation[key]
        changes.append(change)
    removed=set(plan['removed_ids']);inferred={key for change in changes for key in change.get('removed_ids',[])}
    if removed!=inferred:raise ValueError('Export removals do not match retained owner XML: missing owners for '+','.join(sorted(removed-inferred))+'; unexpected '+','.join(sorted(inferred-removed)))
    creations=[];covered=set();objects=metadata_context.context_objects(request['context']);root=next(oid for oid,d in objects.items() if s.val(d[0][3])==s.ZERO)
    def depth(oid):
        return 0 if target[oid]['parent_id']==root else 1+depth(target[oid]['parent_id'])
    declared=set()
    for oid in sorted(plan['new_ids'],key=depth):
        if oid in covered:continue
        record=target[oid];kind=export.runtime_kind(record,target)
        separate_form=kind in preparation.FORM_KINDS and record['parent_id'] in objects
        separate_template=kind in ('Template','CommonTemplate') and record['parent_id'] in objects
        if not (separate_form or separate_template) and (record['parent_id']!=root or kind not in profiles.creation_types()):
            raise ValueError('Unsupported new object tree: '+kind)
        creation=preparation.plan(dict(plan_context,xml_path=str(Path(request['directory'])/record['path'])),batch_relations=True,complete_export=True)
        reverse=profiles.profiles().get(kind,{}).get('reverse_references')
        if reverse:
            reference=record['kind']+'.'+record['name']
            recorders=[row for row in target.values() if row['kind']==reverse['kind'] and any(node.text==reference for node in row['node'].findall(preparation.Q+'Properties/'+preparation.Q+reverse['property']+'/{'+xml_namespaces.READABLE+'}Item'))]
            if not recorders:raise ValueError('New '+kind+' requires a recorder Document in the complete export')
        creations.append(creation);covered.add(oid)
        covered.update(preparation.metadata(form['definition_xml'])[1] for form in creation.get('forms',[]))
        covered.update(preparation.metadata(template['definition_xml'])[1] for template in creation.get('templates',[]))
    for oid in plan['new_ids']:
        node=target[oid]['node'];values=[metadata_context.guid(item.get('uuid')) for item in node.iter() if item.get('uuid')]
        values += [metadata_context.guid(item.text) for item in node.iter() if item.tag in ('{'+xml_namespaces.READABLE+'}TypeId','{'+xml_namespaces.READABLE+'}ValueId')]
        if len(set(values))!=len(values) or declared & set(values):raise ValueError('New objects share declared UUIDs')
        declared.update(values)
    if covered!=new_ids:raise ValueError('New metadata files are not covered by creation converters')
    plan['creation_plans']=creations
    import form_dependencies
    plan['dependent_form_ids']=form_dependencies.candidates(target,changes,objects,request['baseline_directory'])
    plan['snapshot_ids']=[change['object_id'] for change in changes]+plan['removed_ids']
    plan['snapshot_ids']+=plan['dependent_form_ids']
    for parent,record in target.items():
        if parent not in objects:continue
        counts={};children=record['node'].find(preparation.Q+'ChildObjects')
        rules={row['xml_name']:row for row in structure.profile(record['kind'])['collections']}
        for node in ([] if children is None else children):
            rule=rules[node.tag.removeprefix(preparation.Q)]
            if rule['storage']!='stored_name':continue
            matches=[oid for oid,child in target.items() if child['parent_id']==parent and child['kind']==rule['item_type'] and child['name']==node.text]
            if len(matches)!=1:raise ValueError('Ambiguous final child position')
            oid=matches[0];cls=s.val(objects[oid][0][2]) if oid in objects else ids.class_id(export.runtime_kind(target[oid],target))
            position=counts.get(cls,0);counts[cls]=position+1
            if oid in objects and s.val(objects[oid][0][10])!=str(position) and oid not in plan['snapshot_ids']:plan['snapshot_ids'].append(oid)
    if any(creation['kind'] not in preparation.FORM_KINDS|{'Template','CommonTemplate'} for creation in creations):
        plan['snapshot_ids']+=sorted(set(objects)-set(plan['snapshot_ids']))
    else:
        import metadata_references
        for creation in creations:
            if creation['kind'] not in preparation.FORM_KINDS:continue
            reference_plan=metadata_references.plan(dict(context=request['context'],xml=creation['form_xml']))
            for row in reference_plan['objects']:
                if row['object_id'] not in plan['snapshot_ids']:plan['snapshot_ids'].append(row['object_id'])
    if len(set(plan['snapshot_ids']))!=len(plan['snapshot_ids']):raise ValueError('Duplicate changed/deleted object')
    plan['needs_storage']=bool(plan['dependent_form_ids']) or any(change.get('needs_storage') or change['kind'].endswith('Form') or change['kind'] in ('Template','CommonTemplate') for change in changes)
    import metadata_type_references
    plan['needs_storage']=plan['needs_storage'] or any(metadata_type_references.needs_storage(change['object_xml'],request['context'],change['object_id']) for change in changes)
    import external_dependencies
    lost_features=any({s.val(v) for v in objects[change['object_id']][0][13][1:]}-{node.get('uuid') for node in E.fromstring(change['object_xml']).iter() if node.get('uuid')}
                      for change in changes if change['kind'] in profiles.change_types())
    if (plan['removed_ids'] or lost_features) and external_dependencies.has_watchers(objects,plan['removed_ids']):plan['needs_storage']=True
    schema_inputs=creations+[template for creation in creations for template in creation.get('templates',[])]
    if any(creation.get('template_xml') is not None for creation in schema_inputs):
        import template_references
        plan['needs_storage']=plan['needs_storage'] or any(any(template_references.required(creation['template_xml'])) for creation in schema_inputs if creation.get('template_xml') is not None)
    return plan,changes


def without_new_children(text,owner,target,new_ids):
    top,scopes=xml_namespaces.parse(text);children=top[0].find(preparation.Q+'ChildObjects')
    if children is not None:
        names={(target[oid]['kind'],target[oid]['name']) for oid in new_ids if target[oid]['parent_id']==owner}
        for node in list(children):
            if (node.tag.removeprefix(preparation.Q),node.text) in names:children.remove(node)
    return xml_namespaces.render(top,text,scopes)


def create_contents(request,plan,objects,owner_bodies,reference_objects,definitions):
    root=next(oid for oid,d in objects.items() if s.val(d[0][3])==s.ZERO);result={};code=''
    for creation in plan['creation_plans']:
        kind=creation['kind'];r=dict(request,object_id=root,object_type=kind,forms=creation.get('forms',[]),modules=creation.get('modules',{}),
                                   file_data=creation.get('file_data',{}),
                                   templates=creation.get('templates',[]),
                                   inline_modules=creation.get('inline_modules',[]),related_objects=creation.get('related_objects',[]))
        if kind in ('Template','CommonTemplate'):
            import template_serializer
            parent=creation['parent_id']
            r.update(object_id=parent,snapshot=request['snapshots'][parent],original_version=request['originals'][parent],definition_xml=creation['object_xml'])
            for key in ('template_xml','template_data'):
                if key in creation:r[key]=creation[key]
            generated=template_serializer.create(r,contents_only=True)
        elif kind in preparation.FORM_KINDS:
            import managed_form_operations as forms
            parent=creation['parent_id']
            r.update(object_id=parent,snapshot=request['snapshots'][parent],original_version=request['originals'][parent],
                     form_kind='CommonForm' if kind=='CommonForm' else kind.removesuffix('Form'),
                     name=creation['name'],definition_xml=creation['object_xml'],form_xml=creation['form_xml'],_allow_owner_rename=True)
            if creation['module_text'] is not None:r['module_text']=creation['module_text']
            generated=forms.create(r,owner_body=owner_bodies.get(parent),contents_only=True)
        else:
            r['object_xml']=creation['object_xml']
            if kind=='CommonModule':r.update(source_text=creation['module_text'],clear_module_text=creation.get('clear_module_text',False))
            generated=c.serialize(r,reference_objects=reference_objects,batch_relations=True,contents_only=True,definition=definitions[creation['object_id']])
        if generated.version_code:code=generated.version_code
        for oid,compiled in generated.objects.items():
            if oid not in plan['new_ids'] or oid in result:raise ValueError('Unexpected or duplicate creation body')
            # Object converters return stream descriptions scoped to this body.
            result[oid]=compiled
    if set(result)!=set(plan['new_ids']):raise ValueError('Missing newly created body')
    return result,code


def declare_creations(request,plan,objects,reference_objects,reader):
    """Allocate every new native type before compiling any dependent stream."""
    import metadata_object_xml
    import inline_object_xml
    definitions={};root=next(oid for oid,docs in objects.items() if s.val(docs[0][3])==s.ZERO)
    for creation in plan['creation_plans']:
        kind=creation['kind']
        if kind in preparation.FORM_KINDS|{'Template','CommonTemplate'}:continue
        forms={entry['name']:preparation.metadata(entry['definition_xml'])[1] for entry in creation.get('forms',[])}
        templates={entry['name']:preparation.metadata(entry['definition_xml'])[1] for entry in creation.get('templates',[])}
        import metadata_type_references
        types=metadata_type_references.resolve(creation['object_xml'],request)
        import xdto_packages
        xdto_types=xdto_packages.for_web(creation['object_xml'],request,reference_objects)
        allocation=reader.allocations[creation['object_id']]
        definition=metadata_object_xml.prepare_creation(creation['object_xml'],request['platform'],kind,forms,objects,root,reference_objects,templates,type_references=types,allocation=allocation,xdto_types=xdto_types)
        oid,name,body,_=definition.result
        features=inline_object_xml.features(s.Parser(body.decode('utf-8-sig')).documents()[0],profiles.layout(kind,request['platform'])) if kind in profiles.change_types() else []
        reader.register(oid,body,features);definitions[oid]=definition
    return definitions


def content(request,change,objects,owner_bodies=None,reference_objects=None):
    oid=change['object_id'];kind=change['kind'];original=request['originals'][oid]
    r=dict(request,snapshot=request['snapshots'][oid],object_id=oid,parent_id=oid,original_version=original,object_xml=change['object_xml'],
           file_data=change.get('file_data',{}),
           modules=change.get('modules',{}),inline_modules=change.get('inline_modules',[]),removed_modules=change.get('removed_modules',[]),removed_inline_modules=change.get('removed_inline_modules',[]))
    r['_allow_rename']=preparation.metadata(change['object_xml'])[2]!=s.val(objects[oid][0][9])
    r['preserve_content']=change.get('content_unchanged',False)
    if kind in deletion.OWNERS and kind!='Configuration':
        import metadata_owner_profiles as owner_profiles
        if kind in owner_profiles.owner_profiles():
            _,_,baseline,_=export.inventory(request['baseline_directory'])
            before=preparation.read(Path(request['baseline_directory'])/baseline[oid]['path'])
            import metadata_owner_change
            old=E.fromstring(before);new=E.fromstring(change['object_xml'])
            import opaque_owner_references
            checked_old,checked_new=opaque_owner_references.equivalent_roots(old,new,kind,objects,reference_objects)
            if metadata_owner_change.retained_xml(checked_old,kind,ignore_form_properties=True,ignore_common_properties=True)==metadata_owner_change.retained_xml(checked_new,kind,ignore_form_properties=True,ignore_common_properties=True) and not any(r.get(key) for key in ('modules','inline_modules','removed_modules','removed_inline_modules')):
                return metadata_owner_change.serialize(dict(r,object_type=kind,before_xml=before,_removed_children=change.get('removed_ids',[])),native_content=True,reference_objects=reference_objects)
    if kind in deletion.OWNERS:
        if kind not in profiles.change_types() and kind!='Configuration':
            _,_,originals,_=export.inventory(request['baseline_directory'])
            r['before_xml']=preparation.read(Path(request['baseline_directory'])/originals[oid]['path'])
        return deletion.owner_content(r,objects,oid,change.get('removed_ids',[]),reference_objects=reference_objects)
    if kind=='CommonModule':
        import commonmodule_serializer
        return commonmodule_serializer.compile_change(dict(r,source_text=change['module_text'],clear_module_text=change.get('clear_module_text',False)))
    if kind.endswith('Form'):
        import managed_form_operations
        form_request=dict(r,definition_xml=change['object_xml'],storage=request['storage'],_allow_owner_rename=True)
        parent=s.val(objects[oid][0][3])
        if form_request['preserve_content'] and parent in (owner_bodies or {}) and s.val(objects[parent][0][3])!=s.ZERO:
            import form_dependencies
            source=contexts.read(dict(request,snapshot=request['snapshots'][parent]),parent)
            old=s.Parser(s.inflate(source.data).decode('utf-8-sig')).documents()[0]
            delta,_=form_dependencies.binding_delta(old,owner_bodies[parent],ids.class_labels()[s.val(objects[parent][0][2])],objects[parent][0],objects)
            if delta:form_request['preserve_content']=False
        if not form_request['preserve_content'] and (not change.get('interface_unchanged') or parent in (owner_bodies or {}) or change['module_text'] is None):
            form_request['form_xml']=change['form_xml']
        if change['module_text'] is not None:form_request['module_text']=change['module_text']
        return managed_form_operations.compile_change(form_request,owner_body=(owner_bodies or {}).get(parent))
    if kind in ('Template','CommonTemplate'):
        import template_serializer
        r.update(operation='Изменение',definition_xml=change['object_xml'],storage=request['storage'])
        for key in ('template_xml','template_data'):
            if key in change:r[key]=change[key]
        return template_serializer.compile_change(r)
    import object_change_serializer
    return object_change_serializer.serialize(dict(r,object_type=kind),native_content=True,reference_objects=reference_objects)


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
    if not platform_profiles.legacy(request['platform']):raise ValueError('Complete configuration commit requires legacy profile')
    plan,changes=prepare(request)
    if not changes:raise ValueError('Export has no changes to commit')
    if plan['target_fingerprint']!=request['target_fingerprint'] or plan['baseline_fingerprint']!=request['baseline_fingerprint']:
        raise ValueError('Export directories changed after planning')
    objects=metadata_context.context_objects(request['context']);removed=set(plan['removed_ids']);changed={};externals=[];versions={}
    for oid in plan['snapshot_ids']:
        frame=contexts.read(dict(request,snapshot=request['snapshots'][oid]),oid)
        contexts.original_version(request['originals'][oid],frame.metadata)
    _,_,target,_=export.inventory(request['directory'])
    import metadata_targets
    reference_objects=metadata_targets.final(objects,target,allow_rename=True)
    import native_references
    reader=native_references.Catalog(request,reference_objects)
    import xdto_packages
    request=dict(request,_native_references=reader,_xdto_catalog=xdto_packages.from_export(request['directory'],target))
    if any('Rights' in row.get('file_data',{}) for row in changes+plan['creation_plans']):
        import metadata_definitions
        request['_metadata_definitions']=metadata_definitions.from_inventory(target)
    import metadata_object_xml
    for creation in plan['creation_plans']:
        if creation['kind'] not in preparation.FORM_KINDS|{'Template','CommonTemplate'}:
            reader.declare(metadata_object_xml.allocate_creation(creation['object_xml'],request['platform'],creation['kind']))
    # Compile owners first, irrespective of XML inventory order. Forms must bind
    # to final fields/modes, while all version checks use the original storage.
    compiled={change['object_id']:content(request,change,objects,reference_objects=reference_objects) for change in changes if not change['kind'].endswith('Form') and change['kind'] not in ('Template','CommonTemplate')}
    for oid,entry in compiled.items():reader.register(oid,entry.body,native_references.feature_ids(entry.docs[0]))
    definitions=declare_creations(request,plan,objects,reference_objects,reader)
    owner_bodies={change['object_id']:s.Parser(compiled[change['object_id']][1].decode('utf-8-sig')).documents()[0]
                  for change in changes if change['kind'] in deletion.OWNERS}
    import form_dependencies
    changes+=form_dependencies.changes(request,plan,objects,owner_bodies)
    new_contents,version_code=create_contents(request,plan,objects,owner_bodies,reference_objects,definitions) if plan['new_ids'] else ({},'')
    final_objects=copy.deepcopy(objects)
    for oid,(docs,body,streams,ext) in new_contents.items():final_objects[oid]=docs
    desired={}
    for parent,record in target.items():
        rows=[];children=record['node'].find(preparation.Q+'ChildObjects');rules={rule['xml_name']:rule for rule in structure.profile(record['kind'])['collections']}
        for node in ([] if children is None else children):
            rule=rules[node.tag.removeprefix(preparation.Q)]
            if rule['storage']!='stored_name':continue
            matches=[oid for oid,child in target.items() if child['parent_id']==parent and child['kind']==rule['item_type'] and child['name']==node.text]
            if len(matches)!=1:raise ValueError('Ambiguous final child')
            oid=matches[0];rows.append((oid,s.val(final_objects[oid][0][2])))
        desired[parent]=rows
    position_changes=[]
    for parent,pairs in desired.items():
        counts={}
        for oid,cls in pairs:
            index=counts.get(cls,0);counts[cls]=index+1
            if parent in objects and s.val(final_objects[oid][0][10])!=str(index):
                if oid in objects and oid not in {change['object_id'] for change in changes}:position_changes.append(oid)
                final_objects[oid][0][10]=s.atom(index)
    for change in changes:
        oid=change['object_id']
        docs,body,streams,ext=compiled[oid] if oid in compiled else content(request,change,objects,owner_bodies)
        # Native getObjects can omit a child map. Retain the authoritative context
        # and remove children only after the whole owner's body was converted.
        rows={}
        for child,cls in metadata_context.children(objects[oid][0]):
            if child not in removed:rows.setdefault(cls,[]).append(child)
        docs[0][12]=[s.atom(len(rows))]+[[s.atom(cls),s.atom(len(keys))]+[s.atom(key) for key in keys] for cls,keys in rows.items()]
        if plan['new_ids'] and (change['kind'] in deletion.OWNERS or desired[oid]):
            source=s.Parser(s.inflate(contexts.read(dict(request,snapshot=request['snapshots'][oid]),oid).data).decode('utf-8-sig')).documents()[0]
            target_body=s.Parser(body.decode('utf-8-sig')).documents()[0]
            target_body=collections.replace(target_body,source,change['kind'],objects[oid][0],objects,desired[oid],final_objects)
            body=s.native_body_bytes([target_body]);rows={}
            for child,cls in desired[oid]:rows.setdefault(cls,[]).append(child)
            docs[0][12]=[s.atom(len(rows))]+[[s.atom(cls),s.atom(len(keys))]+[s.atom(key) for key in keys] for cls,keys in rows.items()]
        docs[0][10]=copy.deepcopy(final_objects[oid][0][10])
        refs=s.metadata_relations(docs[0][14]);refs={key:flag for key,flag in refs.items() if not (key in removed and flag==1)}
        for child,_ in desired[oid]:
            if child in new_contents:refs[child]=1
        docs[0][14]=[s.atom(len(refs))]+[s.atom(key) for key in refs]+[s.atom(flag) for flag in refs.values()]
        frame=contexts.read(dict(request,snapshot=request['snapshots'][oid]),oid)
        docs[0][15:17]=copy.deepcopy(frame.saved[0][15:17]);docs[1]=copy.deepcopy(frame.saved[1])
        local=packets.content_version(body);original=bytes.fromhex(request['originals'][oid]);packets.commit_metadata(docs[0],original,local)
        changed[oid]=(docs,body,tuple(streams));versions[oid]=(original,local)
        externals.extend(dict(object_id=oid,**entry) for entry in ext)
    for oid in position_changes:
        frame=contexts.read(dict(request,snapshot=request['snapshots'][oid]),oid);docs=frame.docs;body=s.inflate(frame.data)
        import inline_command_xml
        ext=inline_command_xml.preserve_owner_streams(docs,oid,s.Parser(body.decode('utf-8-sig')).documents()[0],ids.class_labels()[s.val(docs[0][2])],request['platform'])
        docs[0][10]=copy.deepcopy(final_objects[oid][0][10]);docs[0][15:17]=copy.deepcopy(frame.saved[0][15:17]);docs[1]=copy.deepcopy(frame.saved[1])
        original=bytes.fromhex(request['originals'][oid]);local=packets.content_version(body);packets.commit_metadata(docs[0],original,local)
        changed[oid]=(docs,body,());versions[oid]=(original,local);externals.extend(dict(object_id=oid,**entry) for entry in ext)
    existing_changed=list(changed)
    for oid,(docs,body,streams,ext) in new_contents.items():
        docs[0][10]=copy.deepcopy(final_objects[oid][0][10]);local=packets.content_version(body);packets.commit_metadata(docs[0],local,local)
        changed[oid]=(docs,body,streams);versions[oid]=(local,local);externals.extend(dict(object_id=oid,**entry) for entry in ext)
    targets=set(removed)
    for oid in removed:targets.update(s.val(key) for key in objects[oid][0][13][1:])
    for oid,(docs,_,_) in changed.items():
        if oid in objects:targets.update({s.val(key) for key in objects[oid][0][13][1:]}-{s.val(key) for key in docs[0][13][1:]})
    kept={oid:copy.deepcopy(docs) for oid,docs in objects.items() if oid not in removed}
    for oid,(docs,body,_) in changed.items():kept[oid]=docs
    def referenced(node):return any(referenced(child) for child in node) if isinstance(node,list) else s.val(node) in targets
    for oid,docs in kept.items():
        if targets & s.metadata_relations(docs[0][14]).keys():raise ValueError('Final configuration has incoming deletion references from '+oid)
        if oid in changed and referenced(s.Parser(changed[oid][1].decode('utf-8-sig')).documents()):raise ValueError('Deleted object remains in final object body')
        if any(child in removed for child,_ in metadata_context.children(docs[0])):raise ValueError('Deleted child remains in final owner metadata')
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
    payload=packets.assemble(final_graph(objects,kept,list(changed),removed,plan['new_ids']),records)
    # Re-read the complete inventories after all companions were consumed.
    final_plan=export.plan(request)
    if final_plan['target_fingerprint']!=plan['target_fingerprint'] or final_plan['baseline_fingerprint']!=plan['baseline_fingerprint']:raise ValueError('Export changed during compilation')
    return dict(data=base64.b64encode(payload).decode(),descriptions=[descriptions[oid] for oid in changed],requested=requested,removed_ids=plan['removed_ids'],
                changed_ids=existing_changed,new_ids=list(new_contents),version_code=version_code,externals=externals,repository=request['repository'],platform=request['platform'],repository_version=request['repository_version'])


def run(request):
    if request.get('mode')=='plan':return prepare(request)[0]
    return serialize(request)


if __name__=='__main__':
    from serializer_cli import run as cli
    cli(run)
