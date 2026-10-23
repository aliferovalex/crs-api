"""Whole restriction text, field matrices and templates from native witnesses."""
import json
from pathlib import Path
import sys
import unittest
from xml.etree import ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / '\u0421\u0435\u0440\u0438\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u044f'))
import native_metadata as s
import role_restrictions_xml as codec
import xml_namespaces


class RoleRestrictionXMLTests(unittest.TestCase):
    def case(self):
        return json.loads(Path(__file__).with_name('fixtures').joinpath('role_restrictions_native.json').read_text())

    def parse(self, text):
        return s.Parser(text).documents()[0]

    def test_independent_native_templates(self):
        case = self.case(); nodes = [E.fromstring(text) for text in case['templates_xml']]
        native = codec.templates(nodes)
        self.assertEqual(s.render(native), case['templates_native'])
        restored = codec.templates_from_native(native)
        self.assertEqual(s.render(codec.templates(restored)), case['templates_native'])
        self.assertEqual(len(restored), 4)

    def test_independent_field_condition_adds_implicit_default(self):
        case = self.case(); path = self.parse(case['field_path']); node = E.fromstring(case['field_xml'])
        native = codec.matrix([node], {'Field': path}.__getitem__)
        self.assertEqual(s.render(native), case['field_native'])
        restored = codec.matrix_from_native(native, lambda value: 'Field')
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0].findtext(codec.Q + 'field'), 'Field')
        self.assertEqual(s.render(codec.matrix(restored, {'Field': path}.__getitem__)), case['field_native'])

    def test_complete_condition_preserves_quotes_and_literal_carriage_returns(self):
        node = E.fromstring('<restrictionByCondition xmlns="http://v8.1c.ru/8.2/roles"><condition>SELECT&#13;X\n&quot;quoted&quot;</condition></restrictionByCondition>')
        native = codec.matrix([node]); restored = codec.matrix_from_native(native)
        self.assertEqual(s.val(native[1][1]), 'SELECT\rX\r\n"quoted"')
        serialized = xml_namespaces.serialize(restored[0])
        self.assertIn('&#13;', serialized)
        reparsed = E.fromstring(serialized)
        self.assertEqual(s.render(codec.matrix([reparsed])), s.render(native))

    def test_legacy_native_double_cr_line_endings_survive_xml_export(self):
        text = '{1,{1,"first\r\r\nsecond\r\r\nthird",0}}'
        native = self.parse(text); restored = codec.matrix_from_native(native)
        xml = xml_namespaces.serialize(restored[0])
        self.assertIn('&#13;\n', xml)
        self.assertEqual(s.render(codec.matrix([E.fromstring(xml)])), text)

    def test_multiple_rows_with_the_same_field_are_not_collapsed(self):
        node = E.fromstring(self.case()['field_xml']); path = self.parse(self.case()['field_path'])
        other = E.fromstring(self.case()['field_xml']); other.find(codec.Q + 'condition').text = 'OTHER'
        native = codec.matrix([node, other], lambda name: path)
        self.assertEqual(s.val(native[0]), '3')
        restored = codec.matrix_from_native(native, lambda path: 'Field')
        self.assertEqual(len(restored), 2)
        self.assertEqual(s.render(codec.matrix(restored, lambda name: path)), s.render(native))

    def test_field_context_is_required_in_both_directions(self):
        node = E.fromstring(self.case()['field_xml']); native = self.parse(self.case()['field_native'])
        with self.assertRaisesRegex(ValueError, 'metadata context'):
            codec.matrix([node])
        with self.assertRaisesRegex(ValueError, 'metadata context'):
            codec.matrix_from_native(native)

    def test_default_and_empty_matrices(self):
        for native in ('{0}', '{1,{1,"",0}}', '{1,{1,"TRUE",0}}'):
            with self.subTest(native=native):
                nodes = codec.matrix_from_native(self.parse(native))
                self.assertEqual(s.render(codec.matrix(nodes)), native)

    def test_empty_global_condition_is_not_confused_with_a_field_default(self):
        native = '{2,{1,"",0},{1,"OTHER",0}}'
        nodes = codec.matrix_from_native(self.parse(native))
        self.assertEqual(len(nodes), 2)
        self.assertEqual(s.render(codec.matrix(nodes)), native)

    def test_unsupported_xml_is_rejected(self):
        q = ' xmlns="http://v8.1c.ru/8.2/roles"'
        for text in ('<restrictionByCondition' + q + '><unknown/></restrictionByCondition>',
                     '<restrictionByCondition' + q + '><condition/><condition/></restrictionByCondition>',
                     '<restrictionByCondition' + q + '>lost<condition/></restrictionByCondition>',
                     '<restrictionByCondition' + q + '><condition value="lost"/></restrictionByCondition>'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                codec.matrix([E.fromstring(text)])

    def test_malformed_native_counts_and_versions_are_rejected(self):
        for text in ('{2,{1,"TRUE",0}}', '{1,{2,"TRUE",0}}', '{1,{1,"TRUE",1}}', '{1,{1,"bare\nLF",0}}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                codec.matrix_from_native(self.parse(text))
        for text in ('{1}', '{1,{"name"}}', '{2,{"same","a"},{"SAME","b"}}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                codec.templates_from_native(self.parse(text))

    def test_field_aliases_cannot_hide_different_native_paths(self):
        case = self.case(); path = self.parse(case['field_path']); other = self.parse(case['field_path'])
        other[1][1] = s.atom('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
        native = self.parse('{3,{1,"",0},{1,"A",1,' + s.render(path) + '},{1,"B",1,' + s.render(other) + '}}')
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            codec.matrix_from_native(native, lambda path: 'Same')


if __name__ == '__main__':
    unittest.main()
