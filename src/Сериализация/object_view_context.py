"""Read view dependencies and bind stored child names; never encode native bodies."""
import uuid
from xml.etree import ElementTree as E
import metadata_identifiers
import metadata_structure
import native_configuration_reader
import native_object_reader
import native_metadata as s
import xml_namespaces


def plan(body, oid, kind, platform):
    kind = 'Form' if kind.endswith('Form') and kind != 'CommonForm' else kind
    profile = metadata_structure.profile(kind)
    documents = s.Parser(body.decode('utf-8-sig')).documents()
    if kind == 'Configuration':
        groups = native_configuration_reader.stored_collections(documents, oid, platform)
    else:
        groups = native_object_reader.stored_collections(documents[0], kind)
    rules = {row['item_class_id']: row for row in profile['collections']
             if row['storage'] == 'stored_name' and row.get('item_class_id')}
    collections = [dict(class_id=key, tag=rules[key]['xml_name'], ids=values) for key, values in groups.items()]
    references = set()
    constants = set(metadata_identifiers.class_labels()) | {s.ZERO, oid}
    def visit(node):
        if isinstance(node, list):
            # Ownership UUIDs are names to resolve, not bodies to download.
            if node and isinstance(node[0], s.Atom) and s.val(node[0]) in groups:
                return
            for child in node: visit(child)
        elif isinstance(node, s.Atom):
            if node.quoted: return  # Comments and other string literals are not links.
            try: value = str(uuid.UUID(s.val(node)))
            except ValueError: return
            if value not in constants: references.add(value)
    visit(documents)
    return dict(collections=collections, references=sorted(references))


def bind_children(raw, oid, collection_plan, descriptions):
    """ibcmd renders properties; history descriptors supply stored child names.

    Keep inline children and all compiler properties unchanged. A missing or
    contradictory name is a conversion failure, never an empty child list.
    """
    if not collection_plan: return raw
    original = raw.decode('utf-8-sig')
    root, scopes = xml_namespaces.parse(original)
    owners = [node for node in root if node.get('uuid') == oid]
    if len(owners) != 1: raise ValueError('Selected XML owner missing')
    owner = owners[0]; q = owner.tag[:owner.tag.rfind('}')+1]
    expected = {}; order = []
    for group in collection_plan:
        names = []
        for child_id in group['ids']:
            child = descriptions.get(child_id)
            if child is None: raise ValueError('Missing stored child name: '+child_id)
            if (child['class_id'], child['parent_id']) != (group['class_id'], oid):
                raise ValueError('Stored child class/parent differs from native declaration')
            name = child['name']
            if not isinstance(name, str) or not name or name in names:
                raise ValueError('Invalid or duplicate stored child name')
            names.append(name)
        if group['tag'] in expected: raise ValueError('Duplicate child collection tag')
        expected[group['tag']] = names; order.append(group['tag'])
    children = owner.find(q+'ChildObjects')
    if children is None:
        if not any(expected.values()): return xml_namespaces.render(root, original, scopes).encode('utf-8')
        children = E.SubElement(owner, q+'ChildObjects')
    existing = {}
    for child in list(children):
        tag = child.tag.removeprefix(q)
        if child.tag != q+tag or tag not in expected: continue
        name = child.text or ''
        if child.attrib or len(child) or name not in expected[tag] or name in existing.setdefault(tag, set()):
            raise ValueError('Compiler child list contradicts native declarations')
        existing[tag].add(name); children.remove(child)
    for tag in order:
        for name in expected[tag]: E.SubElement(children, q+tag).text = name
    return xml_namespaces.render(root, original, scopes).encode('utf-8')
