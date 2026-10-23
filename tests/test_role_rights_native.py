"""Native restrictions have a versioned envelope before the state count."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / '\u0421\u0435\u0440\u0438\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u044f'))
import native_metadata as s
import role_rights_native as rights

READ = '1c87578f-9e09-4ec0-a991-5629c87b1588'
VIEW = 'aa6448f2-be0f-42ea-ba26-1af7f52b5b65'


class NativeRoleRightsTests(unittest.TestCase):
    def parse(self, text):
        return s.Parser(text).documents()[0]

    def test_saved_extended_native_table_keeps_complete_conditions(self):
        case = json.loads(Path(__file__).with_name('fixtures').joinpath('role_rights_extended.json').read_text())
        node = self.parse(case['native']); table = rights.read(node)
        self.assertEqual(dict(table.states), case['states'])
        self.assertTrue(table.extended)
        self.assertEqual(len(table.restrictions), 1)
        self.assertEqual(s.render(rights.write(table)), case['native'])
        # Neither caller mutations nor a later writer may mutate saved conditions.
        output = rights.write(table); output[-1][1][1][1].value = 'CHANGED'
        self.assertEqual(s.render(rights.write(table)), case['native'])

    def test_plain_states_and_extended_empty_tables_are_distinct(self):
        for text in ('{0}', '{1,0,0}', '{0,' + READ + ',1}',
                     '{0,' + READ + ',1,' + VIEW + ',-1}',
                     '{1,1,' + READ + ',1,0}'):
            with self.subTest(text=text):
                node = self.parse(text); table = rights.read(node)
                self.assertEqual(s.render(rights.write(table)), text)
        self.assertFalse(rights.read(self.parse('{0}')).extended)
        self.assertTrue(rights.read(self.parse('{1,0,0}')).extended)

    def test_saved_plain_tables_use_a_version_marker_not_a_count(self):
        case = json.loads(Path(__file__).with_name('fixtures').joinpath('role_rights_plain_851.json').read_text())
        for observation in case['tables']:
            with self.subTest(native=observation['native']):
                table = rights.read(self.parse(observation['native']))
                self.assertFalse(table.extended)
                self.assertEqual(dict(table.states), observation['states'])
                self.assertEqual(s.render(rights.write(table)), observation['native'])

    def test_invalid_counts_duplicates_and_restrictions_fail(self):
        cases = ('{1}', '{1,0}', '{1,0,1}', '{0,' + READ + ',0}',
                 '{0,' + READ + ',1,' + READ + ',-1}', '{0,' + READ + '}',
                 '{2,' + READ + ',1,' + VIEW + ',-1}',
                 '{1,1,' + READ + ',1,1,{' + READ + ',{2,{1,"TRUE",0}}}}',
                 '{1,0,2,{' + READ + ',{0}},{' + READ + ',{0}}}')
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ValueError):
                rights.read(self.parse(text))

    def test_opaque_matrix_can_contain_multiple_complete_rows(self):
        text = '{1,1,' + READ + ',1,1,{' + READ + ',{2,{1,"a""b",0},{1,"other",2,"Field1","Field2"}}}}'
        self.assertEqual(s.render(rights.write(rights.read(self.parse(text)))), text)


if __name__ == '__main__':
    unittest.main()
