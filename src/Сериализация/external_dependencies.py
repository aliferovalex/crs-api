"""Check retained form/schema streams against removed metadata identities."""
import base64,uuid
import external_data
import metadata_identifiers as ids
import native_metadata as s
import native_object_profiles as profiles
import serialization_context as contexts
import native_streams


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
        import native_form_reader
        result=set()
        def visit(node):
            if isinstance(node,list):
                for child in node:visit(child)
            elif not node.quoted:
                try:result.add(str(uuid.UUID(s.val(node))))
                except ValueError:pass
        visit(native_form_reader.interface(raw));return result
    definition=s.Parser(body.decode('utf-8-sig')).documents()[0]
    if not isinstance(definition,list) or len(definition)!=3 or not isinstance(definition[1],list) or len(definition[1])!=3:raise ValueError('Unsupported template dependency definition')
    code=s.val(definition[1][2 if kind=='CommonTemplate' else 1])
    if not code.isdecimal():raise ValueError('Invalid template dependency content kind: '+code)
    if code!='6':return set()  # Other template formats are preserved without reference analysis.
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


def stream_references(kind, object_id, body, streams):
    """Read links only in supported structured streams; payloads are decoded."""
    roles=native_streams.roles(kind,object_id,streams)
    if native_streams.family(kind) in ('Form','CommonForm') and object_id+'.0' not in streams:
        raise ValueError('Missing managed form interface stream: '+object_id)
    result=set()
    for name,role in roles.items():
        if role in ('managed-form','rights','template-content'):
            result.update(stream_ids(kind,body,streams[name]))
    return result


def compiled_targets(index, removed, targets):
    """Expand deletion identities from declarations proved against source CF."""
    import compiled_dependencies
    removed=set(removed);result=set(targets)
    if not removed<=index.inventory.keys():raise ValueError('Deleted object is absent from bound source CF')
    owners=removed|{index.feature_owners[value] for value in result if value in index.feature_owners}
    for oid in sorted(owners):
        record=index.inventory[oid]
        facts=index.facts(oid)
        if oid in removed:
            result.add(oid);result.update(facts.features);result.update(facts.generated)
        else:
            for owner,generated in compiled_dependencies.generated_owners(record).items():
                if owner in result:result.update(generated)
    return result


def validate(request,objects,removed,targets,changed):
    """changed maps UUID to final (docs, body, compressed streams) tuples."""
    removed=set(removed);targets=set(targets)
    if not targets:return
    watchers={oid for oid,docs in objects.items() if oid not in removed and watched(docs[0])}
    watchers.update(oid for oid,entry in changed.items() if oid not in removed and watched(entry[0][0]))
    if not watchers:return
    if '_source_types' not in request:raise ValueError('External deletion validation requires a bound source CF index')
    targets=compiled_targets(request['_source_types'],removed,targets)
    validate_streams(request,objects,watchers,targets,changed)


def validate_streams(request,objects,watchers,targets,changed):
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
                import native_object_reader
                parsed=s.Parser(body.decode('utf-8-sig')).documents()
                if len(parsed)!=1:raise ValueError('Unsupported native dependency body')
                found={str(uuid.UUID(s.val(native_object_reader.at(parsed[0],rule['path'])))) for rule in rules} & targets
                if found:raise ValueError('Final native property references deleted metadata: '+oid+'; '+','.join(sorted(found)))
                continue
        found=stream_references(kind,oid,body,{name:s.inflate(raw) for name,raw in streams.items()}) & targets
        if found:raise ValueError('Final external stream references deleted metadata: '+oid+'; '+','.join(sorted(found)))
