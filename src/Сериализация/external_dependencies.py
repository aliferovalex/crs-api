"""Check retained form/schema streams against removed metadata identities."""
import base64,uuid
import external_data
import metadata_identifiers as ids
import metadata_targets
import native_metadata as s
import native_references
import object_xml_profiles as profiles
import serialization_context as contexts


def watched(metadata):
    kind=ids.class_labels().get(s.val(metadata[2]),'')
    if kind in profiles.profiles() and any(rule.get('relation_flag',0) is None for rule in profiles.layout(kind).get('reference_values',{}).values()):return True
    return (kind.endswith('Form') or kind in ('Template','CommonTemplate','Role')) and s.val(metadata[11][0])!='0'


def has_watchers(objects,removed=()):
    removed=set(removed)
    return any(oid not in removed and watched(docs[0]) for oid,docs in objects.items())


def stream_ids(kind,body,raw):
    if kind=='Role':
        import role_rights_native
        return set(role_rights_native.file_references(raw))
    if kind.endswith('Form'):
        import managed_form_xml
        result=set()
        def visit(node):
            if isinstance(node,list):
                for child in node:visit(child)
            elif not node.quoted:
                try:result.add(str(uuid.UUID(s.val(node))))
                except ValueError:pass
        visit(managed_form_xml.interface(raw));return result
    definition=s.Parser(body.decode('utf-8-sig')).documents()[0]
    if not isinstance(definition,list) or len(definition)!=3 or not isinstance(definition[1],list) or len(definition[1])!=3:raise ValueError('Unsupported template dependency definition')
    code=s.val(definition[1][2 if kind=='CommonTemplate' else 1])
    if code in ('1','4'):return set()  # Text and binary document contents are user data.
    if code!='6':raise ValueError('Unsupported template dependency content kind: '+code)
    import schema_content
    result=set()
    for part in schema_content.unpack(raw):
        doc=schema_content._parse(part)
        for node in doc.getElementsByTagName('*'):
            text=''.join(child.data for child in node.childNodes if child.nodeType==child.TEXT_NODE).strip()
            if node.namespaceURI==schema_content.CORE and node.localName=='TypeId':result.add(str(uuid.UUID(text)))
            elif text.startswith('0:') and (node.localName=='color' or node.getAttributeNS(schema_content.XSI,'type') and schema_content._qname(node,node.getAttributeNS(schema_content.XSI,'type'))==('http://v8.1c.ru/8.1/data/ui','Color')):
                try:result.add(str(uuid.UUID(text[2:])))
                except ValueError:pass
    return result


def validate(request,objects,removed,targets,changed):
    """changed maps UUID to final (docs, body, compressed streams) tuples."""
    removed=set(removed);targets=set(targets)
    if not targets:return
    watchers={oid for oid,docs in objects.items() if oid not in removed and watched(docs[0])}
    watchers.update(oid for oid,entry in changed.items() if oid not in removed and watched(entry[0][0]))
    if not watchers:return
    # Source type/value UUIDs belong to the deleted object's actual definition.
    source_index=metadata_targets.index(objects)
    for oid in removed:
        targets.update(s.val(value) for value in objects[oid][0][13][1:])
        kind=ids.class_labels().get(s.val(objects[oid][0][2]))
        if kind not in profiles.profiles():continue
        layout=profiles.layout(kind,request['platform'])
        if not layout['generated_slots']:continue
        snapshots=request.get('snapshots',{})
        if oid not in snapshots:raise ValueError('Deleted type snapshot is required for external dependencies')
        frame=contexts.read(dict(request,snapshot=snapshots[oid]),oid)
        identity=next(row for row in source_index.targets if row.object_id==oid)
        targets.update(native_references.generated_ids(s.inflate(frame.data),identity,layout))
    # Tabular sections have generated types of their own. Their metadata UUID
    # alone does not protect a form/schema attribute typed as a section or row.
    for oid in (removed|set(changed)) & set(objects):
        if oid not in removed and not targets & {s.val(value) for value in objects[oid][0][13][1:]}:continue
        kind=ids.class_labels().get(s.val(objects[oid][0][2]))
        if kind not in profiles.profiles():continue
        layout=profiles.layout(kind,request['platform'])
        if not layout.get('tabular_collections'):continue
        snapshot=request.get('snapshots',{}).get(oid)
        if snapshot is None and oid in (request.get('object_id'),request.get('parent_id')):snapshot=request.get('snapshot')
        if snapshot is None:raise ValueError('Source owner snapshot is required for tabular dependency types')
        frame=contexts.read(dict(request,snapshot=snapshot),oid);source=s.Parser(s.inflate(frame.data).decode('utf-8-sig')).documents()[0]
        import tabular_section_xml
        for rule in layout['tabular_collections'].values():
            for row in source[rule['slot']][2:]:
                identity=s.val(tabular_section_xml.common(row)[1][2])
                if identity in targets:
                    targets.update(str(uuid.UUID(s.val(value))) for value in row[0][1][1:5])
    needed=watchers & set(objects)
    storage=contexts.decode(request.get('storage'),'External dependencies require current version storage') if needed else None
    current=external_data.extract_many(storage,needed) if needed else {}
    for oid in sorted(watchers):
        streams={};body=None
        if oid in current:
            m=objects[oid][0];record=current[oid]
            if (record['class_id'],record['parent_id'],record['version_number'],record['original'],record['local'])!=(s.val(m[2]),s.val(m[3]),int(s.val(m[5])),uuid.UUID(s.val(m[7])).bytes_le.hex(),uuid.UUID(s.val(m[8])).bytes_le.hex()):raise ValueError('External dependency storage/context mismatch')
            versions={name:uuid.UUID(version).bytes_le.hex()+'00000000' for name,version in contexts.external_versions(m[11]).items()}
            if {row['name']:row['version'] for row in record['externals']}!=versions:raise ValueError('External dependency source stream version mismatch')
            streams={row['name']:base64.b64decode(row['data'],validate=True) for row in record['externals']};body=s.inflate(base64.b64decode(record['data'],validate=True))
        if oid in changed:
            docs,body,payloads=changed[oid][:3]
            streams.update(payloads);m=docs[0]
            group=m[11];expected={s.val(name) for name in group[1::2]}
            if len(group)!=1+2*int(s.val(group[0])) or len(expected)!=int(s.val(group[0])):raise ValueError('Invalid final external dependency stream map')
            streams={key:value for key,value in streams.items() if key in expected}
        else:m=objects[oid][0]
        kind=ids.class_labels()[s.val(m[2])]
        if kind in profiles.profiles():
            rules=[rule for rule in profiles.layout(kind,request['platform']).get('reference_values',{}).values() if rule.get('relation_flag',0) is None]
            if rules:
                import metadata_object_xml
                parsed=s.Parser(body.decode('utf-8-sig')).documents()
                if len(parsed)!=1:raise ValueError('Unsupported native dependency body')
                found={str(uuid.UUID(s.val(metadata_object_xml.at(parsed[0],rule['path'])))) for rule in rules} & targets
                if found:raise ValueError('Final native property references deleted metadata: '+oid+'; '+','.join(sorted(found)))
                continue
        if set(streams)!={oid+'.0'}:raise ValueError('Unsupported external dependency stream map')
        found=stream_ids(ids.class_labels()[s.val(m[2])],body,s.inflate(streams[oid+'.0'])) & targets
        if found:raise ValueError('Final external stream references deleted metadata: '+oid+'; '+','.join(sorted(found)))
