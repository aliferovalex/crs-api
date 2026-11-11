"""Repository contracts for externally compiled, graph-preserving changes.

The compiler owns application contents. Native readers prove identities,
features and dependencies for repository packet metadata.
"""
import copy
import re
from collections import Counter
from xml.etree import ElementTree as E

import metadata_context
import native_content
import native_metadata as s
import export_xml
import serialization_context
import native_streams
import native_features
import native_object_profiles
import metadata_type_references
import native_form_reader
import metadata_references
import native_configuration_reader
import native_object_reader
import compiled_dependencies
import xml_namespaces

OWNERS = {'Catalog', 'Document', 'DataProcessor', 'Report'}

Q = export_xml.Q
FORM = '{http://v8.1c.ru/8.3/xcf/logform}'


def validate_form_xml(text):
    """Check identities in the complete form, independently of control kinds."""
    root=E.fromstring(text)
    if root.tag!=FORM+'Form':raise ValueError('Expected complete managed Form.xml')
    groups=[(root.find(FORM+name),name) for name in ('ChildItems','Attributes','Commands','Parameters')]
    groups.extend((group,'Columns') for group in root.iter(FORM+'Columns'))
    for group,collection in groups:
        if group is None:continue
        ids=set();names=set()
        nodes=(node for node in group.iter() if 'id' in node.attrib) if collection=='ChildItems' else iter(group)
        for node in nodes:
            if 'id' in node.attrib:
                key=node.get('id')
                if not key.isdecimal() or int(key)<=0 or int(key) in ids:raise ValueError('Duplicate or invalid compiled control ID in '+collection)
                ids.add(int(key))
            if 'name' in node.attrib:
                key=node.get('name').casefold()
                if not key or key in names:raise ValueError('Duplicate compiled name in '+collection)
                names.add(key)
    return root


def validate_xml(change, baseline, directory, relative):
    kind = change['kind']
    if kind in OWNERS:
        change['_owner_contract']=True
    if kind.endswith('Form'):
        interface = relative.with_suffix('') / 'Ext/Form.xml'
        target = export_xml.read(directory / interface)
        validate_form_xml(target)
        change['_form_interface'] = target


def guid_counts(node):
    result = Counter()
    def walk(value):
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif not value.quoted and re.fullmatch('[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', s.val(value)):
            key = s.val(value).lower()
            if key != s.ZERO:
                result[key] += 1
    walk(node)
    return result


def validate_graph(frame, oid, objects):
    saved, current = frame.saved[0], frame.metadata
    if s.render(saved[12]) != '{0}' and sorted(metadata_context.children(saved)) != sorted(metadata_context.children(current)):
        raise ValueError('Compiled source child map differs from context')
    for row in (saved, current):
        features = row[13]
        if int(s.val(features[0])) != len(features) - 1 or len({s.val(v) for v in features[1:]}) != len(features) - 1:
            raise ValueError('Invalid compiled source feature map')
    if ({s.val(v) for v in saved[13][1:]} != {s.val(v) for v in current[13][1:]}
            or s.metadata_relations(saved[14]) != s.metadata_relations(current[14])):
        raise ValueError('Compiled source features or relations differ from context')
    parent = s.val(current[3])
    relations = s.metadata_relations(current[14])
    root=parent==s.ZERO and s.val(current[2])==native_configuration_reader.ROOT_CLASS
    if (not root and (parent not in objects or relations.get(parent)!=1)) or s.val(current[4])!=s.ZERO:
        raise ValueError('Invalid compiled source owner relation')
    for child, cls in metadata_context.children(current):
        if child not in objects or s.val(objects[child][0][2]) != cls or s.val(objects[child][0][3]) != oid:
            raise ValueError('Invalid compiled source child identity')


def reconcile_owner(request, change, objects, source, target, docs):
    """Read native feature/type identities; no XML-to-native writer is used."""
    kind = change['kind']; oid = change['object_id']
    layout = native_object_profiles.layout(kind, request['platform'])
    import native_object_reader,metadata_structure
    source_children=native_object_reader.stored_collections(source,kind)
    target_children=native_object_reader.stored_collections(target,kind)
    expected_children={cls:set(children)-set(change.get('_removed_children',{})) for cls,children in source_children.items()}
    for child,row in change.get('_new_children',{}).items():
        cls=next(v['item_class_id'] for v in metadata_structure.profile(kind)['collections'] if row['kind'] in (v['runtime_item_kind'],v['item_type']))
        expected_children.setdefault(cls,set()).add(child)
    if {cls:values for cls,values in expected_children.items() if values}!={cls:set(values) for cls,values in target_children.items() if values}:
        raise ValueError('Compiler changed undeclared stored child identities')
    source_features = native_features.features(source[0], layout)
    target_features = native_features.features(target[0], layout)
    current = {s.val(v) for v in docs[0][13][1:]}
    if set(source_features) != current:
        raise ValueError('Source native features differ from repository metadata')
    final_xml=E.fromstring(change['object_xml'])[0]
    declared={metadata_context.guid(node.get('uuid')) for node in final_xml.iter() if 'uuid' in node.attrib}-{oid}
    if set(target_features)!=declared:raise ValueError('Compiled native features differ from complete XML identities')
    taken=set(objects)
    for row in objects.values():taken.update(s.val(v) for v in row[0][13][1:])
    taken.update(guid_counts(source))
    if (set(target_features)-current)&taken:raise ValueError('New feature UUID collides with an existing identity')
    for slot in layout.get('generated_slots',[]):
        if s.render(source[0][1][slot])!=s.render(target[0][1][slot]):raise ValueError('Compiler changed generated type identity')
    expected_types = set(metadata_type_references.resolve(change['object_xml'], request).values())
    if metadata_type_references.type_ids(target) != expected_types:
        raise ValueError('Compiled reference type IDs differ from current definitions')
    relations = metadata_type_references.reconcile(request, source[0], target[0], layout,
                s.metadata_relations(docs[0][14]), oid, change['object_xml'])
    identities=guid_counts(target)
    for child in change.get('_removed_children',{}):
        if child not in identities:relations.pop(child,None)
    for child in change.get('_new_children',{}):relations[child]=1
    docs[0][13] = [s.atom(len(target_features))] + [s.atom(key) for key in target_features]
    docs[0][14] = [s.atom(len(relations))] + [s.atom(key) for key in relations] + [s.atom(value) for value in relations.values()]


def validate_form_paths(xml, owner, kind):
    paths = native_form_reader.object_paths(owner, kind)
    root,scopes = xml_namespaces.parse(xml)
    main = [node for node in root.findall(FORM + 'Attributes/' + FORM + 'Attribute') if node.findtext(FORM + 'MainAttribute') == 'true']
    if len(main)>1:raise ValueError('Compiled form has multiple main attributes')
    if not main:return None
    alias = main[0].get('name')
    node = main[0].find(FORM + 'Type/' + '{http://v8.1c.ru/8.1/data/core}Type')
    key = None if node is None else metadata_type_references.declared_type(node,scopes)
    if key not in paths.main_types:raise ValueError('Compiled main attribute type differs from its owner')
    for node in root.iter(FORM + 'DataPath'):
        value = node.text or ''
        if value == alias:continue
        if not value.startswith(alias + '.'):
            continue  # Local attributes and parameters are verified by the complete ibcmd round trip.
        if 'Object' + value[len(alias):] not in paths:
            raise ValueError('Compiled form references an unavailable final DataPath: ' + value)
    return paths.main_types[key]


def validate_form_interface(xml,owner,kind,raw,request):
    """Prove main ownership and declared references in a compiled whole form."""
    validate_form_xml(xml)
    expected_main=validate_form_paths(xml,owner,kind)
    form=native_form_reader.interface(raw)
    entries=[v for v in form[3][2:2+int(s.val(form[3][1]))] if s.val(v[10])=='1']
    if expected_main is None:
        if entries:raise ValueError('Compiled native form has an undeclared main attribute')
    elif len(entries)!=1 or s.render(entries[0][5])!='{"Pattern",{"#",'+expected_main+'}}':
        raise ValueError('Compiled native main type differs from final owner')
    storage=serialization_context.decode(request['storage'],'Oversized form storage') if 'storage' in request else None
    values=metadata_references.resolve(xml,request,storage)
    expected=set()
    for value in values.values():expected.update(value if isinstance(value,tuple) else (value,))
    expected.discard(s.ZERO)
    if not expected<=set(guid_counts(form)):
        raise ValueError('Compiled form is missing declared native reference identities')


def content(request, change, objects, before, after):
    oid = change['object_id']
    frame = serialization_context.read(dict(request, snapshot=request['snapshots'][oid]), oid)
    serialization_context.original_version(request['originals'][oid], frame.metadata)
    validate_graph(frame, oid, objects)
    source = s.Parser(before[oid].decode('utf-8-sig')).documents()
    target = s.Parser(after[oid].decode('utf-8-sig')).documents()
    if '_compiled_types' in request and change['kind']!='Configuration' and not change['kind'].endswith('Form'):
        old=request['_source_types'].facts(oid);new=request['_compiled_types'].facts(oid)
        if (old.class_id,old.parent_id,old.name)!=(s.val(frame.metadata[2]),s.val(frame.metadata[3]),s.val(frame.metadata[9])):
            raise ValueError('Compiled source identity differs from repository metadata')
        if set(old.features)!={s.val(value) for value in frame.metadata[13][1:]}:raise ValueError('Compiled source features differ from repository metadata')
        taken=set(objects)|set(request['_source_types'].feature_owners)|set(request['_source_types'].owners)|set(guid_counts(source))
        if (set(new.features)-set(old.features)) & taken:raise ValueError('New metadata feature collides with a source identity')
        docs=copy.deepcopy(frame.docs)
        docs[0][13]=[s.atom(len(new.features))]+[s.atom(value) for value in new.features]
        docs[0][14]=compiled_dependencies.reconcile(request,change,after[oid],after,s.metadata_relations(frame.metadata[14]),before[oid],before)
        names=native_streams.select(docs[0],before.keys()|after.keys())|native_streams.select(frame.metadata,before.keys()|after.keys())
        return native_content.compiled_stream_changes(docs,frame.saved,after[oid],oid,before,after,names)
    if change['kind']=='Configuration':
        old=native_configuration_reader.contained_objects(source,oid,request['platform'])
        new=native_configuration_reader.contained_objects(target,oid,request['platform'])
        if old!=new or set(old.values())!={s.val(v) for v in frame.metadata[13][1:]}:
            raise ValueError('Compiler changed configuration feature identities')
        if '_compiled_types' in request:
            collections=[request['_source_types'].facts(oid).children,request['_compiled_types'].facts(oid).children]
            # A previously unknown class can be inferred only on the nonempty
            # side. Prove its empty native row on the other side as well.
            classes=set().union(*(groups.keys() for groups in collections))
            collections=[native_object_reader.stored_collections(body,'Configuration',classes) for body in (source,target)]
        else:collections=[native_configuration_reader.stored_collections(body,oid,request['platform']) for body in (source,target)]
        expected={key:s.val(row[0][2]) for key,row in objects.items() if s.val(row[0][3])==oid}
        for index,groups in enumerate(collections):
            actual={child:cls for cls,children in groups.items() for child in children}
            wanted={child:cls for child,cls in expected.items() if index==0 or child not in change.get('_removed_children',{})}
            if index:
                import metadata_structure
                if '_compiled_types' in request:
                    import configuration_export
                    wanted.update({child:configuration_export.class_id(row,request['_compiled_types'].inventory) for child,row in change.get('_new_children',{}).items()})
                else:wanted.update({child:metadata_structure.profile(row['kind'])['class_id'] for child,row in change.get('_new_children',{}).items()})
            if actual!=wanted:raise ValueError('Compiled configuration collections differ from repository identities')
        counts=[guid_counts(body) for body in (source,target)]
        for row,groups in zip(counts,collections):
            for cls,children in groups.items():
                row[cls]-=1
                for child in children:row[child]-=1
            if '_compiled_types' not in request:
                for child in change.get('_removed_children',{}):row.pop(child,None)
        counts=[+row for row in counts]
        if '_compiled_types' in request:
            compiled_dependencies.validate_reference_changes(request['_source_types'], request['_compiled_types'], counts[0], counts[1], oid)
            docs=copy.deepcopy(frame.docs)
            docs[0][14]=compiled_dependencies.reconcile(request,change,after[oid],after,
                s.metadata_relations(frame.metadata[14]),before[oid],before)
            return native_content.compiled_stream_changes(docs,frame.saved,after[oid],oid,before,after,
                native_streams.select(docs[0],before.keys()|after.keys()))
        if counts[0]!=counts[1]:raise ValueError('Compiler changed undeclared configuration references')
        docs=copy.deepcopy(frame.docs);relations=s.metadata_relations(docs[0][14]);identities=guid_counts(target)
        for child in change.get('_removed_children',{}):
            if child not in identities:relations.pop(child,None)
        for child in change.get('_new_children',{}):relations[child]=1
        docs[0][14]=[s.atom(len(relations))]+[s.atom(key) for key in relations]+[s.atom(value) for value in relations.values()]
        return native_content.compiled_stream_changes(docs,frame.saved,after[oid],oid,before,after,
                native_streams.select(docs[0],before.keys()|after.keys()))
    if '_owner_contract' not in change and guid_counts(source) != guid_counts(target):
        raise ValueError('Compiler changed definition UUIDs or native references: ' + oid)
    features = {s.val(v) for v in frame.metadata[13][1:]}
    if not features <= set(guid_counts(source)) or oid not in guid_counts(source):
        raise ValueError('Compiled definition does not contain its declared identities')
    docs = copy.deepcopy(frame.docs)
    if change['kind'] in OWNERS:
        if '_owner_contract' in change:reconcile_owner(request, change, objects, source, target, docs)
        names=native_streams.select(docs[0],before.keys()|after.keys())|native_streams.select(frame.metadata,before.keys()|after.keys())
        return native_content.compiled_stream_changes(docs,frame.saved,after[oid],oid,before,after,names)
    name = oid + '.0'
    expected = serialization_context.external_versions(frame.metadata[11])
    if name not in expected or name not in before or name not in after:
        raise ValueError('Compiled form is missing its source or target interface stream')
    parent = s.val(frame.metadata[3]); kind = 'CommonForm' if change['kind']=='CommonForm' else change['kind'][:-4]
    owner = s.Parser(after[parent].decode('utf-8-sig')).documents()[0]
    xml = change.get('_form_interface', change.get('form_xml'))
    validate_form_interface(xml,owner,kind,after[name],request)
    storage = serialization_context.decode(request['storage'], 'Oversized form storage')
    docs[0][14] = metadata_references.form_relations(xml, request, parent, s.metadata_relations(docs[0][14]), before[name], storage)
    names={key for key in before.keys()|after.keys() if key.startswith(oid+'.')}
    return native_content.compiled_stream_changes(docs,frame.saved,after[oid],oid,before,after,names)
