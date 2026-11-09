"""Deletion type identities come from the whole source CF, not class layouts."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest import mock
import zlib

from test_plan_predefined_references import plan_stage
import compiled_dependencies
import compiled_graph
import external_dependencies as dependencies
import metadata_context
import native_metadata as s


class CompiledDeletionDependenciesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved = json.loads((Path(__file__).parent / 'fixtures' / 'compiled_plan_predefined_references.json').read_text(encoding='utf-8'))
        cls.fixture = json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))

    def setup_case(self):
        case = next(row for row in self.fixture['cases'] if row['kind']=='ChartOfCalculationTypes')
        source, target, request = plan_stage(self.fixture, case)
        objects = metadata_context.context_objects(request['context'])
        oid = self.fixture['form_id']; name = oid+'.0'; docs = objects[oid]; a = s.atom
        docs[0][11] = [a(1), a(name, True), a(s.ZERO)]
        metadata = s.text_bytes(docs); body = s.compress(source.image[oid]); stream = s.compress(source.image[name])
        digest = lambda value: a(hashlib.sha1(value).hexdigest(), True)
        storage = s.storage([metadata, body, stream], s.text_bytes([[a(0), a(1), a(oid),
            digest(metadata), digest(body), a(1), a(name, True), digest(stream)]]))
        request.update(storage=base64.b64encode(storage).decode(), snapshots={})
        return case, source, target, request, objects

    def test_form_reference_to_deleted_unprofiled_class_is_rejected(self):
        case, source, target, request, objects = self.setup_case()
        self.assertNotIn(case['kind'], dependencies.profiles.profiles())
        oid = self.fixture['form_id']; name = oid+'.0'
        changed = {oid: (objects[oid], target.image[oid], ((name, s.compress(target.image[name])),))}
        # A missing class profile can no longer silently disable validation.
        without_index = {key: value for key, value in request.items() if key!='_source_types'}
        with self.assertRaisesRegex(ValueError, 'requires a bound source CF index'):
            dependencies.validate(without_index, objects, {case['id']}, {case['id']}, changed)
        with self.assertRaisesRegex(ValueError, 'external stream references deleted metadata'):
            dependencies.validate(request, objects, {case['id']}, {case['id']}, changed)

    def test_cleared_form_reference_allows_the_same_deletion(self):
        case, source, _, request, objects = self.setup_case()
        oid = self.fixture['form_id']; name = oid+'.0'
        changed = {oid: (objects[oid], source.image[oid], ((name, s.compress(source.image[name])),))}
        dependencies.validate(request, objects, {case['id']}, {case['id']}, changed)

    def test_form_companions_do_not_block_or_bypass_deletion_checks(self):
        for clear in (False,True):
            with self.subTest(clear=clear):
                case,source,target,request,objects=self.setup_case()
                oid=self.fixture['form_id'];name=oid+'.0';help_name=oid+'.1'
                docs=copy.deepcopy(objects[oid]);docs[0][11][0]=s.atom(2)
                docs[0][11].extend([s.atom(help_name,True),s.atom(s.ZERO)])
                image=source.image if clear else target.image
                # UUID text in help is user content; the form interface remains checked.
                changed={oid:(docs,image[oid],((name,s.compress(image[name])),
                    (help_name,s.compress(case['id'].encode()))))}
                if clear:
                    dependencies.validate(request,objects,{case['id']},{case['id']},changed)
                else:
                    with self.assertRaisesRegex(ValueError,'external stream references deleted metadata'):
                        dependencies.validate(request,objects,{case['id']},{case['id']},changed)

    def test_removed_object_expands_to_all_its_proven_features_and_generated_ids(self):
        case, source, _, _, _ = self.setup_case()
        with mock.patch.object(dependencies.profiles, 'layout', side_effect=AssertionError('class profile requested')):
            result = dependencies.compiled_targets(source, {case['id']}, {case['id']})
        facts = source.facts(case['id'])
        self.assertEqual(result, {case['id'], *facts.features, *facts.generated})

    def test_inline_types_are_selected_by_declared_feature_ownership(self):
        _, source, _, _, _ = self.setup_case()
        oid, record, owner, expected = next((oid, record, owner, values)
            for oid, record in source.inventory.items()
            for owner, values in compiled_dependencies.generated_owners(record).items()
            if owner!=oid and values)
        with mock.patch.object(dependencies.profiles, 'layout', side_effect=AssertionError('class profile requested')):
            result = dependencies.compiled_targets(source, set(), {owner})
        self.assertEqual(result, {owner, *expected})
        self.assertTrue(expected<=source.facts(oid).generated)

    def test_cf_identity_must_be_proven_before_its_generated_ids_are_used(self):
        case, source, _, _, _ = self.setup_case()
        declared = next(iter(compiled_graph.generated(source.inventory[case['id']])))
        source.image[case['id']] = source.image[case['id']].replace(declared.encode(), b'99999999-9999-4999-8999-999999999999')
        with self.assertRaisesRegex(ValueError, 'absent from compiled CF'):
            dependencies.compiled_targets(source, {case['id']}, {case['id']})

    def test_missing_deleted_source_identity_is_an_error(self):
        _, source, _, _, _ = self.setup_case()
        with self.assertRaisesRegex(ValueError, 'absent from bound source CF'):
            dependencies.compiled_targets(source, {'99999999-9999-4999-8999-999999999999'}, set())


if __name__ == '__main__':
    unittest.main()
