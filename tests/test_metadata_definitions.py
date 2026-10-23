"""Complete XML identities include inline objects without fake stored records."""
import copy
from pathlib import Path
import sys
import unittest
import uuid
from xml.etree import ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / '\u0421\u0435\u0440\u0438\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u044f'))
import metadata_definitions as definitions
import native_metadata as s


def oid(number):
    return str(uuid.UUID(int=number))


def fixture():
    inventory = {}; q = definitions.Q
    def stored(kind, name, number, parent=None):
        node = E.Element(q + kind, uuid=oid(number)); props = E.SubElement(node, q + 'Properties')
        E.SubElement(props, q + 'Name').text = name; E.SubElement(node, q + 'ChildObjects')
        inventory[oid(number)] = dict(id=oid(number), kind=kind, name=name, node=node,
                                      parent_id=s.ZERO if parent is None else parent.get('uuid'))
        if parent is not None:
            E.SubElement(parent.find(q + 'ChildObjects'), q + kind).text = name
        return node
    def inline(parent, kind, name, number):
        node = E.SubElement(parent.find(q + 'ChildObjects'), q + kind, uuid=oid(number))
        props = E.SubElement(node, q + 'Properties'); E.SubElement(props, q + 'Name').text = name
        E.SubElement(node, q + 'ChildObjects')
        return node
    root = stored('Configuration', 'Root', 1)
    catalog = stored('Catalog', 'Items', 2, root)
    subsystem = stored('Subsystem', 'Top', 3, root)
    stored('Subsystem', 'Nested', 4, subsystem)
    stored('Form', 'ItemForm', 5, catalog)
    http = stored('HTTPService', 'API', 6, root)
    url = inline(http, 'URLTemplate', 'Route', 7); inline(url, 'Method', 'Get', 8)
    task = stored('Task', 'Jobs', 9, root); inline(task, 'AddressingAttribute', 'Actor', 10)
    tabular = inline(catalog, 'TabularSection', 'Rows', 11); inline(tabular, 'Attribute', 'Amount', 12)
    inline(catalog, 'Attribute', 'Text', 13)
    return inventory


class MetadataDefinitionTests(unittest.TestCase):
    def test_inline_identity_cannot_claim_its_own_stored_body(self):
        value = definitions.Definition(oid(12), 'Attribute', 'Amount',
                                       'Catalog.Items.TabularSection.Rows.Attribute.Amount',
                                       oid(11), oid(12), False)
        with self.assertRaisesRegex(ValueError, 'stored/inline'):
            definitions.Index([value])

    def test_schema_walk_resolves_stored_and_nested_inline_objects(self):
        index = definitions.from_inventory(fixture())
        field = index.resolve('Catalog.Items.TabularSection.Rows.Attribute.Amount')
        self.assertEqual(field.object_id, oid(12))
        self.assertEqual((field.parent_id, field.stored_id, field.stored), (oid(11), oid(2), False))
        self.assertEqual(index.resolve('Catalog.Items.Form.ItemForm').stored_id, oid(5))
        self.assertEqual(index.resolve('Subsystem.Top.Subsystem.Nested').object_id, oid(4))
        self.assertEqual(index.resolve('HTTPService.API.URLTemplate.Route.Method.Get').object_id, oid(8))
        self.assertEqual(index.resolve('Task.Jobs.AddressingAttribute.Actor').kind, 'AddressingAttribute')
        self.assertEqual(index.by_id(oid(1)).qualified_name, 'Configuration.Root')
        self.assertEqual(len(index.entries), 13)

    def test_children_remain_qualified_and_distinguish_stored_bodies(self):
        index = definitions.from_inventory(fixture())
        fields = index.children('Catalog.Items', {'Attribute'})
        self.assertEqual([entry.object_id for entry in fields], [oid(13)])
        self.assertEqual(index.children(oid(11))[0].object_id, oid(12))
        with self.assertRaisesRegex(ValueError, 'missing'):
            index.resolve('Catalog.Items.Attribute.Missing')

    def test_duplicate_inline_uuid_and_names_are_rejected(self):
        for collision in ('uuid', 'name'):
            inventory = fixture(); children = inventory[oid(2)]['node'].find(definitions.Q + 'ChildObjects')
            node = copy.deepcopy(children[-1])
            if collision == 'uuid':
                node.set('uuid', oid(5)); node.find(definitions.Q + 'Properties/' + definitions.Q + 'Name').text = 'Other'
            else:
                node.set('uuid', oid(50))
            children.append(node)
            with self.subTest(collision=collision), self.assertRaisesRegex(ValueError, 'Duplicate'):
                definitions.from_inventory(inventory)

    def test_partial_or_unregistered_stored_inventory_is_rejected(self):
        inventory = fixture(); del inventory[oid(5)]
        with self.assertRaisesRegex(ValueError, 'Missing'):
            definitions.from_inventory(inventory)
        inventory = fixture(); children = inventory[oid(2)]['node'].find(definitions.Q + 'ChildObjects')
        children.remove(children.find(definitions.Q + 'Form'))
        with self.assertRaisesRegex(ValueError, 'undeclared'):
            definitions.from_inventory(inventory)

    def test_ownership_cycles_and_record_identity_mismatch_are_rejected(self):
        inventory = fixture(); inventory[oid(3)]['parent_id'] = oid(4)
        with self.assertRaisesRegex(ValueError, 'Cyclic'):
            definitions.from_inventory(inventory)
        inventory = fixture(); inventory[oid(2)]['name'] = 'Different'
        with self.assertRaisesRegex(ValueError, 'differs'):
            definitions.from_inventory(inventory)

    def test_unknown_collections_and_duplicate_sections_are_not_ignored(self):
        for mode in ('collection', 'section'):
            inventory = fixture(); node = inventory[oid(2)]['node']
            if mode == 'collection':
                E.SubElement(node.find(definitions.Q + 'ChildObjects'), definitions.Q + 'FutureElement', uuid=oid(50))
            else:
                E.SubElement(node, definitions.Q + 'ChildObjects')
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                definitions.from_inventory(inventory)


if __name__ == '__main__':
    unittest.main()
