"""Final XML identities for stored and inline metadata, without native snapshots.

Collections come from the metadata schema. Recognizing an identity does not
enable serialization of its class or manufacture repository metadata for inline
objects. stored_id identifies the real body that contains each inline element.
"""
from dataclasses import dataclass
from functools import lru_cache
from xml.etree.ElementTree import Element
import metadata_context
import metadata_structure
import native_metadata as s
import xml_namespaces

Q = '{' + xml_namespaces.MD + '}'


@dataclass(frozen=True)
class Definition:
    object_id: str
    kind: str
    name: str
    qualified_name: str
    parent_id: str
    stored_id: str
    stored: bool


class Index:
    def __init__(self, entries):
        self.entries = tuple(entries)
        self._ids = {}; self._names = {}; children = {}; folded = set()
        for entry in self.entries:
            if not isinstance(entry, Definition):
                raise ValueError('Invalid metadata definition')
            if (guid(entry.object_id) != entry.object_id or guid(entry.stored_id) != entry.stored_id
                    or (entry.parent_id != s.ZERO and guid(entry.parent_id) != entry.parent_id)
                    or type(entry.stored) is not bool or entry.stored != exported(entry.kind)
                    or (entry.stored and entry.stored_id != entry.object_id)
                    or (not entry.stored and entry.stored_id == entry.object_id)):
                raise ValueError('Invalid stored/inline metadata identity')
            parts = entry.qualified_name.split('.')
            if len(parts) % 2 or any(not part for part in parts) or parts[-2:] != [entry.kind, entry.name]:
                raise ValueError('Invalid qualified metadata definition name')
            if entry.object_id in self._ids or entry.qualified_name.casefold() in folded:
                raise ValueError('Duplicate metadata definition UUID or name')
            self._ids[entry.object_id] = entry
            self._names[entry.qualified_name] = entry
            folded.add(entry.qualified_name.casefold())
            children.setdefault(entry.parent_id, []).append(entry)
        self._children = {oid: tuple(rows) for oid, rows in children.items()}

    def by_id(self, oid):
        try:
            return self._ids[guid(oid)]
        except KeyError:
            raise ValueError('Metadata definition is missing: ' + str(oid)) from None

    def resolve(self, name):
        try:
            return self._names[name]
        except (KeyError, TypeError):
            raise ValueError('Metadata definition is missing: ' + str(name)) from None

    def children(self, parent, kinds=None):
        oid = self.resolve(parent).object_id if isinstance(parent, str) and '.' in parent else guid(parent)
        self.by_id(oid)
        return tuple(entry for entry in self._children.get(oid, ())
                     if kinds is None or entry.kind in kinds)


def guid(value):
    try:
        return metadata_context.guid(value)
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Invalid metadata definition UUID') from None


@lru_cache(maxsize=None)
def exported(kind):
    return metadata_structure.profile(kind)['exported']


@lru_cache(maxsize=None)
def rules(kind):
    return {row['xml_name']: row for row in metadata_structure.profile(kind)['collections']}


def identity(node, kind, oid=None):
    if not isinstance(node, Element) or node.tag != Q + kind or set(node.attrib) != {'uuid'}:
        raise ValueError('Unexpected metadata definition class or attributes')
    value = guid(node.get('uuid'))
    if oid is not None and value != oid:
        raise ValueError('Metadata definition UUID differs from inventory')
    props = node.findall(Q + 'Properties')
    if len(props) != 1:
        raise ValueError('Missing or duplicate metadata definition Properties')
    names = props[0].findall(Q + 'Name')
    if len(names) != 1 or names[0].attrib or len(names[0]):
        raise ValueError('Missing or duplicate metadata definition Name')
    name = names[0].text or ''
    if not name or '.' in name or '/' in name or '\\' in name:
        raise ValueError('Invalid metadata definition name')
    return value, name


def from_inventory(inventory):
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError('A complete metadata inventory is required')
    records = {}; roots = []
    for key, record in inventory.items():
        if not isinstance(record, dict):
            raise ValueError('Invalid metadata inventory record')
        oid = guid(key)
        if oid in records or guid(record.get('id')) != oid:
            raise ValueError('Duplicate or mismatched metadata inventory UUID')
        kind = record.get('kind'); metadata_structure.profile(kind)
        node = record.get('node')
        if node is None:
            raise ValueError('Metadata inventory node is required')
        _, name = identity(node, kind, oid)
        if record.get('name') != name:
            raise ValueError('Metadata definition name differs from inventory')
        parent = record.get('parent_id')
        if parent == s.ZERO:
            if kind != 'Configuration':
                raise ValueError('Only Configuration can be an inventory root')
            roots.append(oid)
        else:
            parent = guid(parent)
        records[oid] = dict(kind=kind, name=name, node=node, parent=parent)
    if len(roots) != 1:
        raise ValueError('Exactly one Configuration definition is required')
    root = roots[0]; names = {}
    # Iterative parent traversal also handles deeply nested stored subsystems.
    for start in records:
        chain = []; visiting = set(); oid = start
        while oid not in names:
            if oid in visiting:
                raise ValueError('Cyclic metadata inventory ownership')
            if oid not in records:
                raise ValueError('Missing metadata inventory parent')
            visiting.add(oid); chain.append(oid)
            if oid == root:
                break
            oid = records[oid]['parent']
        for oid in reversed(chain):
            record = records[oid]; parent = record['parent']
            prefix = '' if oid == root or parent == root else names[parent] + '.'
            names[oid] = prefix + record['kind'] + '.' + record['name']
    entries = []; registered = set(); stored_children = {}
    for oid, record in records.items():
        key = (record['parent'], record['kind'], record['name'])
        if key in stored_children:
            raise ValueError('Duplicate stored metadata declaration')
        stored_children[key] = oid
        entries.append(Definition(oid, record['kind'], record['name'], names[oid], record['parent'], oid, True))

    def inline(node, kind, parent, stored_id, prefix):
        children = node.findall(Q + 'ChildObjects')
        if len(children) > 1:
            raise ValueError('Duplicate metadata ChildObjects')
        if not children:
            return
        declared = set()
        for child in children[0]:
            tag = child.tag.removeprefix(Q); rule = rules(kind).get(tag)
            if child.tag != Q + tag or rule is None:
                raise ValueError('Unknown metadata child collection: ' + str(tag))
            if rule['storage'] == 'stored_name':
                name = child.text or ''
                if child.attrib or len(child) or not name:
                    raise ValueError('Invalid stored metadata child declaration')
                oid = stored_children.get((parent, rule['item_type'], name))
                if oid is None or oid in registered:
                    raise ValueError('Missing or multiply registered stored metadata child')
                registered.add(oid)
            elif rule['storage'] == 'inline_xml':
                oid, name = identity(child, rule['item_type'])
                full = ('' if parent == root else prefix + '.') + tag + '.' + name
                key = (tag, name.casefold())
                if key in declared:
                    raise ValueError('Duplicate inline metadata declaration')
                declared.add(key)
                entries.append(Definition(oid, rule['item_type'], name, full, parent, stored_id, False))
                inline(child, rule['item_type'], oid, stored_id, full)
            else:
                raise ValueError('Unsupported metadata collection storage')
    for oid, record in records.items():
        inline(record['node'], record['kind'], oid, oid, names[oid])
    if registered != set(records) - {root}:
        raise ValueError('Metadata inventory contains undeclared stored objects')
    return Index(entries)
