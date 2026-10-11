from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/Сериализация'))
import metadata_classes as m

ROOT = '11111111-1111-1111-1111-111111111111'
CLASS = '22222222-2222-2222-2222-222222222222'
CHILD = '33333333-3333-3333-3333-333333333333'
GENERAL = '9cd510cd-abfc-11d4-9434-004095e12fc7'
OTHER = '44444444-4444-4444-4444-444444444444'


def parse(text):
    return m.s.Parser(text).documents()[0]


def root(row=None):
    row = row or '{%s,0}' % CLASS
    return parse('{2,{%s},2,{%s,{1,{0},1,%s}},{%s,{6,{1,{0},1,{%s,1,%s}}}},0}'
                 % (ROOT, GENERAL, row, m.MAIN_GROUP, OTHER, CHILD))


class ClassDiscovery(unittest.TestCase):
    def test_empty_collections_and_unknown_names_are_preserved(self):
        result = m.discover(root(), ROOT, {OTHER: 'TestType'})
        self.assertEqual(len(result['classes']), 3)
        self.assertEqual(result['classes'][1]['object_count'], 0)
        self.assertIsNone(result['classes'][1]['name'])
        self.assertEqual(result['classes'][2]['name'], 'TestType')
        self.assertFalse(result['complete_platform_registry'])
        identifiers = {entry['class_id'] for entry in result['classes']}
        self.assertTrue({CHILD, GENERAL, m.MAIN_GROUP}.isdisjoint(identifiers))

    def test_wrong_root_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'UUID mismatch'):
            m.discover(root(), CHILD)

    def test_malformed_counts_are_rejected(self):
        for path in ((2,), (3, 1, 2), (3, 1, 3, 1)):
            with self.subTest(path=path):
                broken = root()
                node = broken
                for index in path:
                    node = node[index]
                node.value = '8'
                with self.assertRaisesRegex(ValueError, 'count'):
                    m.discover(broken, ROOT)

    def test_duplicate_class_is_rejected(self):
        broken = root()
        broken[4][1][1][3][0].value = CLASS
        with self.assertRaisesRegex(ValueError, 'Duplicate class'):
            m.discover(broken, ROOT)

    def test_duplicate_instance_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate object'):
            m.discover(root('{%s,1,%s}' % (CLASS, CHILD)), ROOT)

    def test_unsupported_structure_is_rejected(self):
        for path in ((0,), (3, 1, 0), (4, 1, 0)):
            broken = root()
            node = broken
            for index in path:
                node = node[index]
            node.value = '999'
            with self.assertRaisesRegex(ValueError, 'Unsupported'):
                m.discover(broken, ROOT)

    def test_unknown_feature_keeps_its_classes(self):
        broken = root()
        broken[3][0].value = '55555555-5555-5555-5555-555555555555'
        self.assertEqual(m.discover(broken, ROOT)['classes'][1]['class_id'], CLASS)


if __name__ == '__main__':
    unittest.main()
