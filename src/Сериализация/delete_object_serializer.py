"""Delete one stored metadata object using its owner's complete target XML."""
import metadata_context
import native_metadata as s
import serialization_context as contexts
import metadata_identifiers as ids
import platform_profiles as platforms
import native_collection_editor as collections
import metadata_structure
import automatic_deletion as automatic


def deletion_target(objects,object_id,parent_id=None):
    """Common planning/serialization guard; embedded features are not objects."""
    oid=metadata_context.guid(object_id)
    if oid not in objects:raise ValueError('Deletion object is missing')
    m=objects[oid][0];kind=ids.class_labels().get(s.val(m[2]));parent=s.val(m[3])
    if kind is None or kind=='Configuration' or parent==s.ZERO:raise ValueError('Cannot delete the Configuration root or an unknown class')
    if s.val(m[4])!=s.ZERO:raise ValueError('Embedded objects cannot be deleted as stored objects')
    if metadata_context.children(m) or any(s.val(d[0][3])==oid for d in objects.values()):raise ValueError('Deletion object has children; delete them first')
    if parent_id is not None and parent!=metadata_context.guid(parent_id):raise ValueError('Deletion object belongs to another parent')
    if parent not in objects:raise ValueError('Deletion parent is missing')
    parent_kind=ids.class_labels().get(s.val(objects[parent][0][2]))
    if parent_kind not in metadata_structure.automatic_owners():raise ValueError('Unsupported deletion parent')
    rules=collections.rules(parent_kind)
    if not any(rule['runtime_item_kind']==kind and rule['item_class_id']==s.val(m[2])
               and rule['native']['status'] in ('verified_profile','snapshot_collection') for rule in rules):
        raise ValueError('Unsupported deletion parent collection')
    if (oid,s.val(m[2])) not in metadata_context.children(objects[parent][0]):raise ValueError('Deletion object is not registered with its parent')
    # Relations to contained feature UUIDs (e.g. EnumValue) are dependencies too.
    features=m[13]
    if int(s.val(features[0]))!=len(features)-1:raise ValueError('Invalid deletion feature count')
    targets={oid}|{metadata_context.guid(s.val(v)) for v in features[1:]}
    for key,docs in objects.items():
        if key==oid:continue
        refs=s.metadata_relations(docs[0][14])
        blocked={target for target in targets & refs.keys() if not (key==parent and target==oid and refs[target]==1)}
        if blocked:
            if key==parent:raise ValueError('Deleted object is selected by an owner reference; clear it before deletion')
            raise ValueError('Deletion has incoming references from '+key)
    return oid,parent,kind,parent_kind


def serialize(request):
    """The explicit single-leaf API shares the automatic deletion packet builder."""
    if not platforms.legacy(request['platform']):raise ValueError('Object deletion requires the legacy profile')
    objects=metadata_context.context_objects(request['context'])
    oid,parent,kind,parent_kind=deletion_target(objects,request.get('object_id',request.get('form_id')))
    def snapshot(key,object_id,original):
        frame=contexts.read(request,object_id,'Oversized deletion snapshot','Deletion snapshot/context mismatch',snapshot_key=key)
        contexts.original_version(original,frame.metadata,'Deletion source version mismatch')
        return frame
    frame=snapshot('snapshot',parent,request['original_version'])
    child_key='object_snapshot' if 'object_snapshot' in request else 'form_snapshot'
    snapshot(child_key,oid,request.get('object_original_version',request.get('form_original_version')))
    if s.metadata_relations(frame.saved[0][14])!=s.metadata_relations(frame.metadata[14]):raise ValueError('Parent relations differ')
    if automatic.missing(request['object_xml'],parent,objects)!=[oid]:
        raise ValueError('Explicit deletion XML must remove exactly the selected object')
    source=s.Parser(s.inflate(frame.data).decode('utf-8-sig')).documents()[0]
    expected=collections.edit(source,parent_kind,frame.metadata,objects,[oid])
    targets={oid}|{s.val(key) for key in objects[oid][0][13][1:]}
    def referenced(node):
        return any(referenced(child) for child in node) if isinstance(node,list) else s.val(node) in targets
    if referenced(expected):raise ValueError('Deleted object is selected by an owner reference; clear it before deletion')
    def validate_owner(docs,body,streams,externals):
        # Keep the explicit API's existing contract: only one child is removed.
        # The whole-XML automatic entry point also allows owner property changes.
        if (s.render(s.Parser(body.decode('utf-8-sig')).documents())!=s.render([expected])
                or s.render(docs[0][13])!=s.render(frame.metadata[13])
                or streams or any(entry['action']!=0 for entry in externals)):
            raise ValueError('Deletion XML must preserve all other '+parent_kind+' properties, attributes and streams')
    prepared=dict(request,parent_id=parent,removed_ids=[oid],snapshots={oid:request[child_key]})
    return automatic.serialize(prepared,validate_owner=validate_owner)


def main():
    from serializer_cli import run
    run(serialize)


if __name__=='__main__':main()
