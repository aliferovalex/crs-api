"""Standard fields use scoped negative codes and real metadata owners."""
import json
import base64
from pathlib import Path
import sys
import unittest
from xml.etree import ElementTree as E
sys.path.insert(0, str(next(p for p in (Path(__file__).resolve().parents[1] / 'src').iterdir() if (p / 'role_metadata_context.py').exists())))
import metadata_definitions as definitions
import native_metadata as s
import role_metadata_context as metadata
import role_rights_native as native
import role_rights_xml as rights
import object_file_content as files
from test_metadata_definitions import fixture, oid


def case(name='role_standard_attributes_851.json'):
    return json.loads(Path(__file__).with_name('fixtures').joinpath(name).read_text(encoding='utf-8'))


def context(data):
    return metadata.Context(definitions.Index(definitions.Definition(**entry) for entry in data['definitions']))


def semantic(raw):
    body = s.Parser(raw).documents()[0]
    result = {}
    for header, value in body[1][1:]:
        table = native.read(value)
        matrices = {key: [(s.val(row[0]), s.val(row[1]), frozenset(s.render(path) for path in row[3:])) for row in matrix[1:]]
                    for key, matrix in table.restrictions}
        result[s.render(header)] = dict(table.states), matrices
    return result, s.render(body[2:])


class StandardRoleAttributeTests(unittest.TestCase):
    def test_all_61_independent_headers_and_complete_files_round_trip(self):
        data = case(); ctx = context(data)
        self.assertEqual(len(data['samples']), 61)
        self.assertEqual(len({row['kind'] for row in data['samples']}), 9)
        for sample in data['samples']:
            with self.subTest(kind=sample['kind'], field=sample['field']):
                header = ctx.reference(sample['target'])
                self.assertEqual(s.render(header), sample['native'])
                self.assertEqual(ctx.reference_name(header), sample['target'])
                self.assertEqual(ctx.definition(sample['target']).object_id, sample['owner_id'])
                compiled = rights.compile(sample['xml'], ctx)
                self.assertEqual(semantic(compiled.decode('utf-8-sig')), semantic(sample['body']))
                self.assertEqual(native.file_references(compiled), frozenset({sample['owner_id']}))

    def test_negative_codes_are_scoped_by_owner_kind(self):
        ctx = context(case())
        code = ctx.reference('Catalog.ProbeCatalog.StandardAttribute.Code')
        number = ctx.reference('Document.ProbeDocument.StandardAttribute.Number')
        ref = ctx.reference('Catalog.ProbeCatalog.StandardAttribute.Ref')
        self.assertEqual(s.val(code[3][0]), '-2')
        self.assertEqual(s.val(number[3][0]), '-2')
        self.assertEqual(s.val(ref[3][0]), '-8')
        self.assertNotEqual(ctx.reference_name(code), ctx.reference_name(number))

    def test_all_59_exported_standard_rls_fields_preserve_complete_conditions(self):
        data = case('role_standard_rls_851.json'); ctx = context(data)
        self.assertEqual(len(data['samples']), 59)
        for sample in data['samples']:
            with self.subTest(kind=sample['kind'], field=sample['field']):
                path = ctx.field_path(sample['owner'], sample['field'])
                self.assertEqual(len(path[1]), 1)
                self.assertEqual(ctx.field_name(sample['owner'], path), sample['field'])
                selection = ctx.field(sample['owner'], sample['field'])
                self.assertEqual(selection.definition.object_id, sample['owner_id'])
                self.assertIsNotNone(selection.standard_code)
                compiled = rights.compile(sample['xml'], ctx)
                self.assertEqual(semantic(compiled.decode('utf-8-sig')), semantic(sample['body']))
                self.assertEqual(native.file_references(compiled), frozenset({sample['owner_id']}))

    def test_native_export_omissions_are_not_silently_enabled_for_rls(self):
        data = case('role_standard_rls_851.json'); ctx = context(data)
        self.assertEqual({(row['kind'], row['field']) for row in data['unsupported']},
                         {('AccumulationRegister', 'RecordType'), ('DocumentJournal', 'Type')})
        for sample in data['unsupported']:
            with self.subTest(kind=sample['kind']), self.assertRaisesRegex(ValueError, 'Unsupported standard role restriction field'):
                rights.compile(sample['input_xml'], ctx)

    def test_preparation_keeps_only_real_owner_and_root_definitions(self):
        for filename in ['role_standard_attributes_851.json', 'role_standard_rls_851.json']:
            data = case(filename); ctx = context(data)
            for sample in data['samples']:
                rows = rights.required_definitions(sample['xml'], ctx.definitions)
                self.assertEqual({row['object_id'] for row in rows}, {sample['owner_id'], ctx.definition(sample['owner']).parent_id})
                self.assertTrue(all(row['stored'] for row in rows))
                self.assertTrue(all(row['kind'] != 'StandardAttribute' for row in rows))

    def test_attribute_named_standardattribute_does_not_change_reference_grammar(self):
        inventory = fixture(); q = definitions.Q
        inventory[oid(2)]['node'].find(q + 'Properties/' + q + 'Name').text = 'StandardAttribute'
        inventory[oid(2)]['name'] = 'StandardAttribute'
        child = inventory[oid(1)]['node'].find(q + 'ChildObjects/' + q + 'Catalog'); child.text = 'StandardAttribute'
        ctx = metadata.Context(definitions.from_inventory(inventory))
        name = 'Catalog.StandardAttribute.Attribute.Text'
        header = ctx.reference(name)
        self.assertEqual(len(header), 4)
        self.assertEqual(s.val(header[1]), oid(13))
        self.assertEqual(ctx.reference_name(header), name)

    def test_invalid_standard_headers_and_codes_are_rejected(self):
        ctx = context(case()); name = 'Catalog.ProbeCatalog.StandardAttribute.Code'
        for mutate in [lambda h: h.__setitem__(2, s.atom(0)), lambda h: h.__setitem__(4, s.atom(0)),
                       lambda h: h[3].__setitem__(0, s.atom(-999)), lambda h: h[3].__setitem__(1, s.atom(oid(100)))]:
            header = ctx.reference(name); mutate(header)
            with self.assertRaises(ValueError):ctx.reference_name(header)
        with self.assertRaisesRegex(ValueError, 'Unmapped standard'):
            ctx.reference('Catalog.ProbeCatalog.StandardAttribute.Unknown')
        with self.assertRaises(ValueError):ctx.field_name('Catalog.ProbeCatalog', [[s.atom(0)], [s.atom(-999)]])

    def test_ambiguous_ordinary_and_standard_field_names_are_rejected(self):
        inventory = fixture(); q = definitions.Q
        node = next(child for child in inventory[oid(2)]['node'].find(q + 'ChildObjects') if child.get('uuid') == oid(13))
        node.find(q + 'Properties/' + q + 'Name').text = 'Code'
        ctx = metadata.Context(definitions.from_inventory(inventory))
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            ctx.field_path('Catalog.Items', 'Code')
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            ctx.field_name('Catalog.Items', [[s.atom(0)], [s.atom(-2)]])

    def test_dependency_reader_rejects_invalid_signed_field_codes(self):
        sample = case('role_standard_rls_851.json')['samples'][0]
        for code in ['-0', '-02', '1', '-2147483649', '-2222222222222222222222']:
            with self.subTest(code=code):
                body = s.Parser(sample['body']).documents()[0]
                table = native.read(body[1][1][1])
                matrix = table.restrictions[0][1]
                matrix[2][3][1][0] = s.atom(code)
                body[1][1][1] = native.write(table)
                with self.assertRaisesRegex(ValueError, 'standard restriction field code'):
                    native.file_references(s.native_body_bytes([body]))

    def test_file_dependencies_match_native_standard_permission_and_rls_descriptors(self):
        data = case('role_standard_relations_851.json')
        self.assertEqual(len(data['samples']), 2)
        for sample in data['samples']:
            with self.subTest(role=sample['name']):
                content = files.convert('Role', sample['definition_xml'], {'Rights': base64.b64encode(sample['xml'].encode()).decode()},
                                        {'metadata_definitions': data['definitions']})
                metadata_row = [s.atom(0) for _ in range(17)]; metadata_row[3] = s.atom(sample['parent_id'])
                files.apply_relations(metadata_row, content)
                self.assertEqual(s.metadata_relations(metadata_row[14]), sample['relations'])
                self.assertNotIn(metadata.standard_profile()['class_id'], sample['relations'])


if __name__ == '__main__':
    unittest.main()
