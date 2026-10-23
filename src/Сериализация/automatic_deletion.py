"""Complete owner XML is authoritative for separately stored children."""
import configuration_xml
import metadata_context
import xml_namespaces
import base64,copy,uuid
from xml.etree import ElementTree as E
import native_metadata as s
import metadata_identifiers as ids
import packet_builder as packets
import serialization_context as contexts
import metadata_structure
import native_collection_editor as collections

Q='{'+xml_namespaces.MD+'}'
OWNERS=metadata_structure.automatic_owners()


def missing(text,owner,objects,*,reference_objects=None):
    root=E.fromstring(text);kind=metadata_structure.profile(root[0].tag.removeprefix(Q))['runtime_name']
    if kind not in OWNERS:return []
    children=root[0].find(Q+'ChildObjects')
    if children is None:raise ValueError('Complete owner XML requires ChildObjects (empty for no children)')
    if children.attrib or (children.text or '').strip():raise ValueError('Invalid owner ChildObjects')
    pairs=metadata_context.children(objects[owner][0]);groups={}
    for oid,cls in pairs:
        label=ids.class_labels().get(cls)
        if label is None:raise ValueError('Unknown stored child class')
        tag='Form' if label.endswith('Form') and label!='CommonForm' else metadata_structure.profile(label)['xml_name']
        name=s.val(objects[oid][0][9])
        if reference_objects is not None:
            import metadata_targets
            matches=[row for row in metadata_targets.index(reference_objects).targets if row.object_id==oid]
            if len(matches)>1:raise ValueError('Ambiguous final child identity')
            if matches:
                row=matches[0]
                if row.class_id!=cls or row.parent_id!=owner:raise ValueError('Final child ownership differs from source')
                name=row.name
        groups.setdefault(tag,[]).append((oid,name))
    allowed=set(groups)
    if kind=='Configuration':allowed.update(row['xml_name'] for row in metadata_structure.profile(kind)['collections'])
    else:allowed.update(('Form','Template'))
    wanted={};seen=set()
    for node in children:
        tag=node.tag.removeprefix(Q)
        if tag not in allowed:
            if kind=='Configuration' or not node.attrib:raise ValueError('Unknown child collection: '+tag)
            continue # Inline Attribute/TabularSection/Command are converted by the owner.
        if node.tag!=Q+tag or node.attrib or len(node) or not node.text or (node.tail or '').strip():raise ValueError('Invalid stored child name')
        key=(tag,node.text)
        if key in seen:raise ValueError('Duplicate stored child name')
        seen.add(key);wanted.setdefault(tag,[]).append(node.text)
    removed=[]
    for tag,items in groups.items():
        names=[name for _,name in items];target=wanted.get(tag,[])
        if len(names)!=len(set(names)):raise ValueError('Ambiguous stored child names')
        if set(target)-set(names):raise ValueError('New stored children require their own creation package')
        if [name for name in names if name in target]!=target:raise ValueError('Stored child order cannot change implicitly')
        removed.extend(oid for oid,name in items if name not in target)
    if set(wanted)-set(groups):raise ValueError('New stored children require their own creation package')
    return removed


def subtree(objects,roots):
    removed=[];visiting=set()
    def visit(oid):
        if oid in visiting:raise ValueError('Cyclic deletion tree')
        if oid in removed:return
        visiting.add(oid)
        m=objects[oid][0]
        if s.val(m[4])!=s.ZERO or s.val(m[3])==s.ZERO:raise ValueError('Cannot delete root or embedded object')
        pairs=metadata_context.children(m)
        actual={(key,s.val(d[0][2])) for key,d in objects.items() if s.val(d[0][3])==oid}
        if actual!=set(pairs):raise ValueError('Deletion tree/context child maps differ')
        removed.append(oid)
        for child,cls in pairs:
            if child not in objects or s.val(objects[child][0][2])!=cls:raise ValueError('Missing deletion child')
            visit(child)
        visiting.remove(oid)
    for oid in roots:visit(oid)
    return removed


def owner_content(request,objects,parent,removed,*,reference_objects=None):
    frame=contexts.read(request,parent);kind=ids.class_labels()[s.val(frame.metadata[2])]
    source=s.Parser(s.inflate(frame.data).decode('utf-8-sig')).documents()[0]
    if kind=='Configuration':
        root=E.fromstring(request['object_xml']);children=root[0].find(Q+'ChildObjects')
        for oid in removed:
            if s.val(objects[oid][0][3])==parent:E.SubElement(children,Q+metadata_structure.profile(ids.class_labels()[s.val(objects[oid][0][2])])['xml_name']).text=s.val(objects[oid][0][9])
        restored=xml_namespaces.serialize(root)
        native=[source];common=configuration_xml.common_properties(native,parent,request['platform'])
        baseline=configuration_xml.configuration_baseline_from_snapshot(restored,parent,common,native,request['platform'],request['context'],reference_objects=reference_objects)
        configuration_xml.xml_property_patches(baseline,restored,parent,common,native,request['platform'],allow_unchanged=True,allow_rename=request.get('_allow_rename',False))
        text=s.inflate(frame.data).decode('utf-8-sig')
        for start,end,value in sorted(configuration_xml.configuration_xml_values(restored,parent,common,native,request['platform'],allow_rename=request.get('_allow_rename',False)),reverse=True):text=text[:start]+value+text[end:]
        docs=frame.docs;streams=[];ext=packets.preserve_external_versions(docs,parent)
        docs[0][9]=s.atom(root[0].findtext(Q+'Properties/'+Q+'Name'),True)
        raw=b'\xef\xbb\xbf'+text.encode('utf-8')
        from native_content import ObjectContent
        return ObjectContent(docs,collections.edit_raw(raw,kind,frame.metadata,objects,removed),streams,ext)
    import object_xml_profiles
    if kind not in object_xml_profiles.profiles():
        import metadata_owner_change
        return metadata_owner_change.serialize(dict(request,object_type=kind,object_id=parent,_removed_children=removed),native_content=True,reference_objects=reference_objects)
    import object_change_serializer as changes
    return changes.serialize(dict(request,object_type=kind,object_id=parent,_removed_children=removed),native_content=True,reference_objects=reference_objects)


def serialize(request,validate_owner=None):
    import platform_profiles
    if not platform_profiles.legacy(request['platform']):raise ValueError('Automatic deletion requires legacy profile')
    objects=metadata_context.context_objects(request['context']);parent=metadata_context.guid(request['parent_id'])
    roots=missing(request['object_xml'],parent,objects);removed=subtree(objects,roots)
    if not roots or removed!=request['removed_ids']:raise ValueError('Automatic deletion plan changed')
    snapshots=request['snapshots']
    for oid in removed:
        frame=contexts.read(dict(request,snapshot=snapshots[oid]),oid)
        if ids.class_labels().get(s.val(frame.metadata[2])) is None:raise ValueError('Unknown deleted class')
    docs,body,streams,ext=owner_content(request,objects,parent,removed)
    if validate_owner is not None:validate_owner(docs,body,streams,ext)
    targets=set(removed)
    for oid in removed:targets.update(s.val(key) for key in objects[oid][0][13][1:])
    # Inline removals from the retained owner must also have no remaining users.
    targets.update({s.val(key) for key in objects[parent][0][13][1:]}-{s.val(key) for key in docs[0][13][1:]})
    relations=s.metadata_relations(docs[0][14])
    relations={key:flag for key,flag in relations.items() if not (key in removed and flag==1)}
    docs[0][14]=[s.atom(len(relations))]+[s.atom(key) for key in relations]+[s.atom(flag) for flag in relations.values()]
    for oid,source in objects.items():
        if oid in removed:continue
        current=docs if oid==parent else source
        if targets & s.metadata_relations(current[0][14]).keys():raise ValueError('Deletion has incoming references from '+oid)
    def referenced(node):return any(referenced(child) for child in node) if isinstance(node,list) else s.val(node) in targets
    if referenced(s.Parser(body.decode('utf-8-sig')).documents()):raise ValueError('Deleted object remains in target owner contents')
    import external_dependencies
    external_dependencies.validate(request,objects,removed,targets,{parent:(docs,body,streams)})
    old_relations=[s.graph_relations(oid,d[0][14]) for oid,d in objects.items()]
    pairs=metadata_context.children(objects[parent][0]);rows={}
    for oid,cls in pairs:
        if oid not in removed:rows.setdefault(cls,[]).append(oid)
    docs[0][12]=[s.atom(len(rows))]+[[s.atom(cls),s.atom(len(keys))]+[s.atom(key) for key in keys] for cls,keys in rows.items()]
    local=packets.content_version(body);original=contexts.original_version(request['original_version'],objects[parent][0])
    packets.commit_metadata(docs[0],bytes.fromhex(original),local)
    kept={oid:copy.deepcopy(d) for oid,d in objects.items() if oid not in removed};kept[parent]=docs
    descriptions=[]
    for oid,d in kept.items():
        if oid==parent:before,after=bytes.fromhex(original),local
        else:
            before=uuid.UUID(s.val(d[0][7])).bytes_le+bytes(4);after=uuid.UUID(s.val(d[0][8])).bytes_le+bytes(4)
            d[0][7]=s.atom(base64.b64encode(before).decode());d[0][8]=s.atom(base64.b64encode(after).decode());d[0][5]=s.atom(4294967295);d[0][6]=s.atom(0)
        descriptions.append(packets.description(d[0],before,after))
    graph=packets.deletion_graph(objects,kept,parent,removed,pairs,old_relations)
    payload=packets.assemble(graph,[packets.ObjectRecord(parent,s.text_bytes(docs),s.compress(body),tuple(streams))])
    return dict(data=base64.b64encode(payload).decode(),object_id=roots[0],parent_id=parent,removed_ids=removed,
                descriptions=descriptions,version_code='',externals=[dict(object_id=parent,**entry) for entry in ext])


if __name__=='__main__':
    from serializer_cli import run
    run(serialize)
