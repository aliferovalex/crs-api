"""Complete XML roles use independently compiled headers, states and flags."""
import json
from pathlib import Path
import sys
import unittest
from xml.etree import ElementTree as E
sys.path.insert(0, str(next(p for p in (Path(__file__).resolve().parents[1] / 'src').iterdir() if (p / 'role_rights_xml.py').exists())))
import metadata_definitions as definitions
import role_metadata_context
import role_right_identifiers as ids
import role_rights_native as native
import role_rights_xml as rights
import native_metadata as s
import xml_namespaces
from test_metadata_definitions import fixture, oid


def case():
    return json.loads(Path(__file__).with_name('fixtures').joinpath('role_rights_xml_851.json').read_text(encoding='utf-8'))


def source(objects='', templates='', flags=('false', 'true', 'false')):
    return ('<Rights xmlns="http://v8.1c.ru/8.2/roles" version="2.21">' +
            ''.join('<%s>%s</%s>' % (tag, value, tag) for tag, value in zip(rights.FLAGS, flags)) + objects + templates + '</Rights>')


def obj(name='Catalog.Items', right='Read', value='true', conditions=''):
    return ('<object><name>' + name + '</name><right><name>' + right + '</name><value>' + value + '</value>' + conditions + '</right></object>')


def document(raw):
    return s.Parser(raw.decode('utf-8-sig')).documents()[0]


class RoleRightsXMLTests(unittest.TestCase):
    def context(self):
        return role_metadata_context.Context(definitions.from_inventory(fixture()))

    def test_complete_independent_configurator_files_match(self):
        data = case()
        context = role_metadata_context.Context(definitions.Index(definitions.Definition(**row) for row in data['definitions']))
        self.assertEqual(len(data['samples']), 23)
        for sample in data['samples']:
            with self.subTest(right=sample['right']):
                actual = document(rights.compile(sample['xml'], context))
                expected = s.Parser(sample['native']).documents()[0]
                self.assertEqual(s.val(actual[0]), '10')
                self.assertEqual(s.render(actual[2:]), s.render(expected[2:]))
                # Native tables are UUID maps: do not use list order to assign
                # rights or require retention of historical XML ordering.
                states = lambda rows: {s.render(row[0]): dict(native.read(row[1]).states) for row in rows[1:]}
                self.assertEqual(states(actual[1]), states(expected[1]))

    def test_complete_conditions_templates_and_flags_are_compiled_together(self):
        conditions = '<restrictionByCondition><field>Text</field><condition>WHERE &quot;X&quot;\n= 1</condition></restrictionByCondition>'
        template = '<restrictionTemplate><name>Filter</name><condition>SELECT\n&quot;X&quot;</condition></restrictionTemplate>'
        body = document(rights.compile(source(obj(conditions=conditions), template, ('true', 'false', 'true')), self.context()))
        table = native.read(body[1][1][1])
        self.assertEqual(dict(table.states), {ids.right_id('Read'): 1})
        self.assertTrue(table.extended)
        matrix = dict(table.restrictions)[ids.right_id('Read')]
        self.assertEqual(s.render(matrix), '{2,{1,"",0},{1,"WHERE ""X""\r\n= 1",1,{{0},{0,' + oid(13) + '}}}}')
        self.assertEqual(s.render(body[2]), '{1,{"Filter","SELECT\r\n""X"""}}')
        self.assertEqual([s.val(value) for value in body[3:]], ['1', '4294967295', '1', '4294967295'])

    def test_empty_role_and_explicit_denial_are_supported(self):
        body = document(rights.compile(source(flags=('false', 'false', 'false'))))
        self.assertEqual(s.render(body), '{10,{0},{0},4294967295,4294967295,0,4294967295}')
        table = native.read(document(rights.compile(source(obj(value='false')), self.context()))[1][1][1])
        self.assertEqual(dict(table.states), {ids.right_id('Read'): -1})

    def test_unknown_objects_standard_selectors_and_missing_context_fail(self):
        for name in ['Catalog.Missing', 'Catalog.Items.StandardAttribute.Unknown']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                rights.compile(source(obj(name=name)), self.context())
        with self.assertRaisesRegex(ValueError, 'final XML metadata'):
            rights.compile(source(obj()))

    def test_unknown_sections_duplicates_and_invalid_values_are_rejected(self):
        invalid = [source(obj(right='UnknownRight')), source(obj(value='yes')), source(obj() + obj()),
                   source(obj(conditions='<unknown/>')), source(templates='<unknown/>'),
                   source(flags=('false', 'unknown', 'false')),
                   source(obj()).replace('</right>', '<name>View</name></right>'),
                   source(obj()).replace('</object>', '<right><name>Read</name><value>false</value></right></object>'),
                   source().replace('version="2.21"', 'version="3.0"'),
                   '<!DOCTYPE Rights>' + source(), source().replace('<setForNewObjects>', 'text<setForNewObjects>')]
        for xml in invalid:
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                rights.parse(xml)

    def test_qname_type_prefix_is_checked_against_its_namespace(self):
        xml = source().replace('version="2.21"', 'version="2.21" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:r="http://v8.1c.ru/8.2/roles" xsi:type="r:Rights"')
        rights.parse(xml)
        with self.assertRaisesRegex(ValueError, 'type'):
            rights.parse(xml.replace('xmlns:r="http://v8.1c.ru/8.2/roles"', 'xmlns:r="urn:wrong"'))

    def test_literal_carriage_returns_remain_distinct_from_xml_line_breaks(self):
        xml = source(obj(conditions='<restrictionByCondition><condition>A&#13;B\nC</condition></restrictionByCondition>'))
        matrix = native.read(document(rights.compile(xml, self.context()))[1][1][1]).restrictions[0][1]
        self.assertEqual(s.val(matrix[1][1]), 'A\rB\r\nC')

    def test_dependency_reader_ignores_right_ids_and_guids_in_query_text(self):
        condition = '<restrictionByCondition><condition>WHERE &quot;' + oid(13) + '&quot; = &quot;X&quot;</condition></restrictionByCondition>'
        raw = rights.compile(source(obj(conditions=condition)), self.context())
        self.assertEqual(native.file_references(raw), frozenset({oid(2)}))
        with self.assertRaisesRegex(ValueError, 'object count'):
            native.file_references(raw.replace(b'{1,', b'{2,', 1))

    def test_standard_attribute_marker_is_not_a_metadata_uuid_dependency(self):
        marker = '03f171e8-326f-41c6-9fa5-932a0b12cddf'
        text = '{10,{1,{{1,' + oid(2) + ',1,{-2,' + marker + '},1},{0,' + ids.right_id('View') + ',1}}},{0},4294967295,1,0,4294967295}'
        self.assertEqual(native.file_references(text.encode()), frozenset({oid(2)}))


if __name__ == '__main__':
    unittest.main()
