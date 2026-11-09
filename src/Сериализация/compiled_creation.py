"""Repository metadata for new objects; all application contents come from CF."""
import base64
import copy

import compiled_metadata
import metadata_structure
import metadata_type_references
import native_streams
import native_content
import native_metadata as s
import native_object_profiles as profiles
import native_object_reader
import native_references
import native_form_reader
import metadata_references
import packet_builder
import compiled_graph
import compiled_dependencies
import configuration_export


def allocate(request,change,objects,image,root_saved,inventory):
    kind=change['kind'];oid=change['object_id'];record=change['_record']
    form=record['kind'] in ('Form','CommonForm')
    if oid in objects:raise ValueError('Creation UUID already exists')
    facts=compiled_graph.read(record,inventory,image,request['platform'])
    parent_kind=inventory[facts.parent_id]['kind']
    parent=facts.parent_id;cls=facts.class_id
    if parent not in objects or s.val(objects[parent][0][2])!=configuration_export.class_id(inventory[parent],inventory):
        raise ValueError('Created object requires the declared parent class')
    raw=image[oid];features=facts.features
    if len(features)!=len(set(features)) or oid in features:raise ValueError('Duplicate created feature identity')
    parent_body=s.Parser(image[parent].decode('utf-8-sig')).documents()
    groups=native_object_reader.stored_collections(parent_body,parent_kind,(cls,))
    if oid not in groups.get(cls,[]):raise ValueError('Created object is absent from the native parent collection')
    version=packet_builder.content_version(raw);encoded=base64.b64encode(version).decode();a=s.atom
    m=[a(6),a(oid),a(cls),a(parent),a(s.ZERO),a(4294967295),a(0),a(encoded),a(encoded),a(record['name'],True),
       a(groups[cls].index(oid)),[a(0)],[a(0)],[a(len(features))]+[a(key) for key in features],
       [a(1),a(parent),a(1)],a((s.val(objects[parent][0][15]) if parent_kind!='Configuration' else '')+cls+'.'+record['name'],True),a(0)]
    docs=[m,copy.deepcopy(root_saved[1]),[a(0)]]
    names=native_streams.select(m,image)
    if form:
        if oid+'.0' not in image:raise ValueError('Created managed form has no interface stream')
        native_form_reader.interface(image[oid+'.0'])
    return native_content.compiled_stream_changes(docs,copy.deepcopy(docs),raw,oid,{},image,names)


def finalize(request,change,entry):
    if change['kind'].endswith('Form'):
        parent=s.val(entry.docs[0][3])
        reader=native_references.catalog(request)
        identity=next(row for row in reader.targets.targets if row.object_id==parent)
        owner=s.Parser(reader.load(identity,label='Form owner').body.decode('utf-8-sig')).documents()[0]
        raw=next(s.inflate(value) for name,value in entry.streams if name==change['object_id']+'.0')
        kind='CommonForm' if change['kind']=='CommonForm' else change['kind'][:-4]
        compiled_metadata.validate_form_interface(change['form_xml'],owner,kind,raw,request)
        entry.docs[0][14]=metadata_references.form_relations(change['form_xml'],request,parent,{parent:1})
        return entry
    if '_compiled_types' in request:
        image={change['object_id']:entry.body}
        image.update({name:s.inflate(payload) for name,payload in entry.streams})
        entry.docs[0][14]=compiled_dependencies.reconcile(request,change,entry.body,image)
        return entry
    oid=change['object_id'];layout=profiles.layout(change['kind'],request['platform'])
    body=s.Parser(entry.body.decode('utf-8-sig')).documents()[0]
    if metadata_type_references.type_ids(body)!=set(metadata_type_references.resolve(change['object_xml'],request).values()):
        raise ValueError('Created reference type UUIDs differ from final configuration')
    relations={s.val(entry.docs[0][3]):1}
    relations.update(native_object_reader.reference_dependencies(body,layout,oid))
    reader=native_references.catalog(request)
    for key in metadata_type_references.object_ids(change['object_xml'],reader):
        if key!=oid:relations.setdefault(key,0)
    known={row.object_id for row in reader.targets.targets}
    if set(relations)-known:raise ValueError('Created object has unresolved repository dependencies')
    entry.docs[0][14]=[s.atom(len(relations))]+[s.atom(key) for key in relations]+[s.atom(value) for value in relations.values()]
    return entry
