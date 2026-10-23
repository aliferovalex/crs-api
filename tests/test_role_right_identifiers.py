"""Identifier assignments must follow independent native observations."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(next(p for p in (ROOT / 'src').iterdir() if (p / 'role_right_identifiers.py').exists())))
import role_right_identifiers as identifiers
SPEC = importlib.util.spec_from_file_location('role_mapping', ROOT / 'tools/map_role_rights.py')
mapping = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mapping)


class RightIdentifierTests(unittest.TestCase):
    def test_profile_follows_saved_independent_observations(self):
        case = json.loads((ROOT / 'tests/fixtures/role_right_identifiers_851.json').read_text(encoding='utf-8'))
        result = mapping.infer(case['samples'])
        self.assertEqual(result['conflicts'], [])
        self.assertEqual(result['collisions'], {})
        self.assertEqual(result['unresolved'], {})
        self.assertEqual(result['resolved'], dict(identifiers.profile()))
        self.assertEqual(len(result['resolved']), 69)
        self.assertEqual(mapping.infer(list(reversed(case['samples'])))['resolved'], result['resolved'])

    def test_identifiers_round_trip_and_are_not_mutable(self):
        for name, identifier in identifiers.profile().items():
            self.assertEqual(identifiers.right_id(name), identifier)
            self.assertEqual(identifiers.right_name(identifier), name)
        with self.assertRaises(TypeError):
            identifiers.profile()['Read'] = 'changed'
        self.assertEqual(identifiers.right_id('Read'), '1c87578f-9e09-4ec0-a991-5629c87b1588')
        self.assertEqual(identifiers.right_id('ThinClient'), '3c00c6ee-844e-4620-85e4-671e72f114d9')
        self.assertEqual(identifiers.right_id('WebClient'), 'bd33c881-192c-4ef7-a51d-b146e38c5078')

    def test_single_right_probes_change_the_expected_native_uuid(self):
        case = json.loads((ROOT / 'tests/fixtures/role_right_identifiers_851.json').read_text(encoding='utf-8'))
        self.assertEqual(len(case['probes']), 23)
        single_changes = 0
        for probe in case['probes']:
            off, on = (case['samples'][probe[key]] for key in ('off', 'on'))
            identifier = identifiers.right_id(probe['right'])
            with self.subTest(right=probe['right']):
                self.assertFalse(off['xml'][probe['right']])
                self.assertTrue(on['xml'][probe['right']])
                self.assertEqual(off['native'][identifier], -1)
                self.assertEqual(on['native'][identifier], 1)
                changed = {key for key in off['native'].keys() | on['native'].keys()
                           if off['native'].get(key) != on['native'].get(key)}
                self.assertIn(identifier, changed)
                single_changes += len(changed) == 1
        self.assertEqual(single_changes, 20)

    def test_unknown_names_and_identifiers_are_rejected(self):
        for value in ['read', 'UnknownRight', '', None, []]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                identifiers.right_id(value)
        for value in ['00000000-0000-0000-0000-000000000000', 'bad', None, []]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                identifiers.right_name(value)

    def test_invalid_profiles_and_aliases_are_rejected(self):
        for data in [{}, {'version': True, 'rights': {}}, {'version': 1, 'rights': {}},
                     {'version': 1, 'rights': {'Read': 'bad'}},
                     {'version': 1, 'rights': {'Read': None}},
                     {'version': 1, 'rights': {'Read': '00000000-0000-0000-0000-000000000000'}},
                     {'version': 1, 'rights': {'Read': '1c87578f-9e09-4ec0-a991-5629c87b1588', 'View': '1c87578f-9e09-4ec0-a991-5629c87b1588'}}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                identifiers.validate(data)


if __name__ == '__main__':
    unittest.main()
