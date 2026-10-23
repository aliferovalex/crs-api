"""Role object and field references use actual XML identities and ownership."""
import json
from pathlib import Path
import sys
import unittest
from xml.etree import ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / '\u0421\u0435\u0440\u0438\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u044f'))
import metadata_definitions as definitions
import native_metadata as s
import role_metadata_context as metadata
import role_restrictions_xml as restrictions
from test_metadata_definitions import fixture, oid


class RoleMetadataContextTests(unittest.TestCase):
    def parse(self, text):
        return s.Parser(text).documents()[0]

    def context(self):
        return metadata.Context(definitions.from_inventory(fixture()))

    def test_independent_native_headers_from_both_legacy_versions(self):
        for file in ('role_reference_headers_851.json', 'role_reference_headers_8327.json'):
            case = json.loads(Path(__file__).with_name('fixtures').joinpath(file).read_text())
            index = definitions.Index(definitions.Definition(**{key: value for key, value in row.items() if key != 'native'}) for row in case['samples'])
            context = metadata.Context(index)
            for row in case['samples']:
                with self.subTest(file=file, kind=row['kind']):
                    self.assertEqual(s.render(context.reference(row['qualified_name'])), row['native'])
                    self.assertEqual(context.reference_name(self.parse(row['native'])), row['qualified_name'])

    def test_direct_fields_and_headers_share_the_same_definition_uuid(self):
        context = self.context(); path = context.field_path('Catalog.Items', 'Text')
        header = context.reference('Catalog.Items.Attribute.Text')
        self.assertEqual(s.val(path[1][1]), s.val(header[1]))
        self.assertEqual(s.val(header[3]), '1')
        self.assertEqual(context.field_name('Catalog.Items', path), 'Text')
        self.assertEqual(s.val(context.reference('Catalog.Items.TabularSection.Rows')[3]), '1')
        self.assertEqual(s.val(context.reference('Task.Jobs.AddressingAttribute.Actor')[3]), '1')

    def test_real_resource_restriction_uses_context_instead_of_custom_paths(self):
        case = json.loads(Path(__file__).with_name('fixtures').joinpath('role_restrictions_native.json').read_text())
        inventory = fixture(); q = definitions.Q; field_id = s.val(self.parse(case['field_path'])[1][1])
        node = E.Element(q + 'InformationRegister', uuid=oid(14)); props = E.SubElement(node, q + 'Properties')
        E.SubElement(props, q + 'Name').text = 'Versions'; children = E.SubElement(node, q + 'ChildObjects')
        field = E.SubElement(children, q + 'Resource', uuid=field_id); props = E.SubElement(field, q + 'Properties')
        E.SubElement(props, q + 'Name').text = 'Field'
        inventory[oid(14)] = dict(id=oid(14), kind='InformationRegister', name='Versions', parent_id=oid(1), node=node)
        E.SubElement(inventory[oid(1)]['node'].find(q + 'ChildObjects'), q + 'InformationRegister').text = 'Versions'
        context = metadata.Context(definitions.from_inventory(inventory)); owner = 'InformationRegister.Versions'
        built = restrictions.matrix([E.fromstring(case['field_xml'])], lambda name: context.field_path(owner, name))
        self.assertEqual(s.render(built), case['field_native'])
        restored = restrictions.matrix_from_native(built, lambda path: context.field_name(owner, path))
        self.assertEqual(restored[0].findtext(restrictions.Q + 'field'), 'Field')

    def test_foreign_fields_and_wrong_header_flags_are_rejected(self):
        context = self.context(); path = context.field_path('Catalog.Items', 'Text')
        with self.assertRaisesRegex(ValueError, 'another metadata owner'):
            context.field_name('Task.Jobs', path)
        header = context.reference('Catalog.Items'); header[3] = s.atom(1)
        with self.assertRaisesRegex(ValueError, 'differs'):
            context.reference_name(header)

    def test_standard_and_nested_selectors_are_not_silently_mapped_to_the_owner(self):
        context = self.context()
        header = [s.atom(1), s.atom(oid(2)), s.atom(1), [s.atom(-2), s.atom(oid(50))], s.atom(1)]
        with self.assertRaisesRegex(ValueError, 'standard or nested'):
            context.reference_name(header)
        with self.assertRaisesRegex(ValueError, 'standard or nested'):
            context.field_name('Catalog.Items', [[s.atom(0)], [s.atom(-2), s.atom(oid(50))]])
        path = context.field_path('Catalog.Items', 'Rows.Amount')
        self.assertEqual(s.render(path), '{{0,' + oid(11) + '},{0,' + oid(12) + '}}')
        self.assertEqual(context.field_name('Catalog.Items', path), 'Rows.Amount')

    def test_missing_or_untyped_definitions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'definition index'):
            metadata.Context({})
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.context().reference('Catalog.Missing')


if __name__ == '__main__':
    unittest.main()
