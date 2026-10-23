"""Keep inferred rights independent from list order and correlated grants."""
import importlib.util
import json
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('map_role_rights', Path(__file__).resolve().parents[1] / 'tools/map_role_rights.py')
mapping = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mapping)
A = '11111111-1111-4111-8111-111111111111'
B = '22222222-2222-4222-8222-222222222222'
C = '33333333-3333-4333-8333-333333333333'


class RoleRightMappingTests(unittest.TestCase):
    def test_saved_independent_native_observations(self):
        witness = json.loads(Path(__file__).with_name('fixtures').joinpath('role_rights_witnesses_851.json').read_text(encoding='utf-8'))
        result = mapping.infer(witness['samples'])
        self.assertEqual(result['resolved'], witness['expected_resolved'])
        self.assertEqual(sorted(result['unresolved']), witness['expected_unresolved'])
        self.assertEqual(result['conflicts'], [])
        self.assertEqual(result['collisions'], {})
        self.assertEqual(len(result['resolved']), 10)
        self.assertEqual(len(result['unresolved']), 45)
        self.assertEqual(mapping.infer(list(reversed(witness['samples'])))['resolved'], result['resolved'])

    def test_correlated_rights_remain_unresolved(self):
        result = mapping.infer([{'xml': {'Read': True, 'View': True}, 'native': {A: 1, B: 1}}])
        self.assertEqual(result['resolved'], {})
        self.assertEqual(result['unresolved'], {'Read': [A, B], 'View': [A, B]})

    def test_unique_assignments_propagate_through_a_chain(self):
        candidates = {'Read': {A}, 'View': {A, B}, 'Edit': {B, C}}
        self.assertEqual(mapping.propagate(candidates),
                         {'Read': {A}, 'View': {B}, 'Edit': {C}})
        self.assertEqual(candidates['View'], {A, B})

    def test_conflicting_assignments_do_not_propagate(self):
        candidates = {'Read': {A}, 'View': {A}, 'Edit': {A, B}}
        self.assertEqual(mapping.propagate(candidates), candidates)

    def test_assignments_can_expose_an_impossible_candidate_set(self):
        candidates = {'Read': {A}, 'View': {B}, 'Edit': {A, B}}
        self.assertEqual(mapping.propagate(candidates)['Edit'], set())

    def test_complete_native_table_with_restrictions_is_accepted(self):
        case = json.loads(Path(__file__).with_name('fixtures').joinpath('role_rights_extended.json').read_text())
        read = '1c87578f-9e09-4ec0-a991-5629c87b1588'
        result = mapping.infer([{'xml': {'Read': True}, 'native': case['native']},
                                {'xml': {'Read': True}, 'native': {read: 1}}])
        self.assertEqual(result['resolved'], {'Read': read})

    def test_independent_values_resolve_without_using_order(self):
        samples = [{'xml': {'Read': True, 'View': True}, 'native': {B: 1, A: 1}},
                   {'xml': {'View': False, 'Read': True}, 'native': {B: -1, A: 1}}]
        result = mapping.infer(samples)
        self.assertEqual(result['resolved'], {'Read': A, 'View': B})
        self.assertEqual(mapping.infer(list(reversed(samples)))['resolved'], result['resolved'])
        self.assertEqual(mapping.infer([samples[i] for i in result['evidence']])['resolved'], result['resolved'])

    def test_inconsistent_observations_do_not_create_a_mapping(self):
        result = mapping.infer([{'xml': {'Read': True}, 'native': {A: 1}},
                                {'xml': {'Read': False}, 'native': {A: 1}}])
        self.assertEqual(result['resolved'], {})
        self.assertEqual(result['conflicts'], ['Read'])

    def test_two_names_cannot_silently_alias_a_native_right(self):
        result = mapping.infer([{'xml': {'Read': True, 'View': True}, 'native': {A: 1}}])
        self.assertEqual(result['resolved'], {})
        self.assertEqual(result['collisions'], {A: ['Read', 'View']})

    def test_invalid_native_state_and_xml_boolean_are_rejected(self):
        for sample in [{'xml': {'Read': 'true'}, 'native': {A: 1}},
                       {'xml': {'Read': True}, 'native': {A: True}},
                       {'xml': {'Read': True}, 'native': {'not-a-uuid': 1}},
                       {'xml': {'Read': True}, 'native': {A: 0}}]:
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                mapping.infer([sample])


if __name__ == '__main__':
    unittest.main()
