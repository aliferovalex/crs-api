"""Native plan streams and complete forms compiled/accepted by real tools."""
import base64
import hashlib
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree as E
import zlib

from test_predefined_references import reference_request
import compiled_graph as graph
import compiled_metadata as compiled
import ibcmd_backend
import metadata_references as references
import metadata_context
import metadata_identifiers as identifiers
import native_metadata as s
import native_predefined_reader as predefined


def plan_stage(data, case):
    before = {name: base64.b64decode(raw) for name, raw in data['image'].items()}
    after = dict(before)
    after.update({name: base64.b64decode(raw) for name, raw in case['changes'].items()})
    for name in case['removed']:after.pop(name)
    def index(image):
        return graph.TypeIndex({r['id']: dict(r, node=E.fromstring(r['xml'])) for r in data['records']}, image)
    source, target = index(before), index(after)
    return source, target, reference_request(target, source)


class PlanPredefinedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved = json.loads((Path(__file__).parent / 'fixtures' / 'compiled_plan_predefined_references.json').read_text(encoding='utf-8'))
        cls.fixture = json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))

    def stage(self, case):
        return plan_stage(self.fixture, case)

    def test_native_and_compiled_plan_streams_prove_the_same_real_value_uuids(self):
        for case in self.fixture['cases']:
            with self.subTest(kind=case['kind']):
                source, target, _ = self.stage(case)
                name = case['id'] + predefined.FAMILIES[case['kind']][1]
                for index in (source, target):
                    self.assertEqual(predefined.read(index.image[name], case['kind']), {'First': case['value']})
                    self.assertEqual(index.facts(case['id']).object_id, case['id'])

    def test_named_value_empty_ref_and_complete_native_form_use_verified_types(self):
        for case in self.fixture['cases']:
            with self.subTest(kind=case['kind']):
                _, target, request = self.stage(case)
                prefix = case['kind'] + '.' + case['name']
                type_id, owner = target.reference('cfg:' + case['kind'] + 'Ref.' + case['name'])
                self.assertEqual(owner, case['id'])
                self.assertEqual(references.resolve_values(case['form_xml'], request),
                                 {prefix + '.First': (type_id, case['value']), prefix + '.EmptyRef': (type_id, s.ZERO)})
                parent = self.fixture['form_owner_id']
                definition = s.Parser(target.image[parent].decode('utf-8-sig')).documents()[0]
                compiled.validate_form_interface(case['form_xml'], definition, 'Catalog',
                    target.image[self.fixture['form_id'] + '.0'], request)

    def test_plan_dependencies_are_added_and_removed_as_owner_objects(self):
        for case in self.fixture['cases']:
            with self.subTest(kind=case['kind']):
                _, target, request = self.stage(case)
                parent = self.fixture['form_owner_id']
                result = references.form_relations(case['form_xml'], request, parent, {})
                self.assertEqual(s.metadata_relations(result), {parent: 1, case['id']: 1})
                # This form is the source of the next edit, which removes the value.
                request['_source_types'] = target
                result = references.form_relations('<Form/>', request, parent, s.metadata_relations(result),
                                                   target.image[self.fixture['form_id'] + '.0'])
                self.assertEqual(s.metadata_relations(result), {parent: 1})

    def test_plan_selects_native_metadata_uuids_using_schema_class_aliases(self):
        for case in self.fixture['cases']:
            with self.subTest(kind=case['kind']):
                _, _, request = self.stage(case)
                result = references.plan(dict(request, xml=case['form_xml']))
                self.assertEqual(result['objects'], [dict(object_id=case['id'], name=case['name'])])
                self.assertEqual(identifiers.class_id(case['kind']),
                                 identifiers.class_id(graph.metadata_structure.profile(case['kind'])['runtime_name']))
        with self.assertRaisesRegex(ValueError, 'Unknown metadata class'):
            identifiers.class_id('UnknownPlanClass')

    def test_current_version_storage_profiles_and_calculation_cf_requirement(self):
        for case in self.fixture['cases']:
            with self.subTest(kind=case['kind']):
                _, target, request = self.stage(case)
                owner = case['id']; name = owner + predefined.FAMILIES[case['kind']][1]
                objects = metadata_context.context_objects(request['context']); docs = objects[owner]; a = s.atom
                docs[0][11] = [a(1), a(name, True), a(s.ZERO)]
                metadata = s.text_bytes(docs); body = s.compress(target.image[owner]); stream = s.compress(target.image[name])
                digest = lambda value: a(hashlib.sha1(value).hexdigest(), True)
                storage = s.storage([metadata, body, stream], s.text_bytes([[a(0), a(1), a(owner),
                    digest(metadata), digest(body), a(1), a(name, True), digest(stream)]]))
                context = s.storage([s.text_bytes(row) for row in objects.values()], s.text_bytes([[a(0)]]))
                source_request = dict(context=base64.b64encode(context).decode(), platform='8.5.1.1529')
                if case['kind']=='ChartOfCalculationTypes':
                    with self.assertRaisesRegex(ValueError, 'requires a compiled CF index'):
                        references.resolve_values(case['form_xml'], source_request, storage)
                    continue
                self.assertEqual(references.resolve_values(case['form_xml'], source_request, storage),
                                 references.resolve_values(case['form_xml'], request))

    def test_missing_values_and_mismatched_form_value_uuids_are_rejected(self):
        for case in self.fixture['cases']:
            with self.subTest(kind=case['kind']):
                _, target, request = self.stage(case)
                with self.assertRaisesRegex(ValueError, 'predefined value is missing'):
                    references.resolve_values(case['form_xml'].replace('.First', '.Missing'), request)
                name = case['id'] + predefined.FAMILIES[case['kind']][1]
                target.image[name] = target.image[name].replace(case['value'].encode(), b'99999999-9999-4999-8999-999999999999')
                parent = self.fixture['form_owner_id']
                definition = s.Parser(target.image[parent].decode('utf-8-sig')).documents()[0]
                with self.assertRaisesRegex(ValueError, 'missing declared native reference identities'):
                    compiled.validate_form_interface(case['form_xml'], definition, 'Catalog',
                        target.image[self.fixture['form_id'] + '.0'], request)

    def test_real_characteristic_column_ids_and_calculation_root_extension_are_validated(self):
        for case in self.fixture['cases']:
            source, _, _ = self.stage(case)
            name = case['id'] + predefined.FAMILIES[case['kind']][1]
            docs = s.Parser(source.image[name].decode('utf-8-sig')).documents()
            if case['kind'] == 'ChartOfCharacteristicTypes':
                self.assertEqual(s.val(docs[0][1][1][1][0]), '1')
                docs[0][1][1][1][0] = s.atom(0)
            elif case['kind'] == 'ChartOfCalculationTypes':
                self.assertEqual(s.render(docs[0][3]), '{0,0}')
                docs[0][3][0] = s.atom(1)
            else:continue
            with self.subTest(kind=case['kind']), self.assertRaises(ValueError):
                predefined.read(s.native_body_bytes(docs), case['kind'])

    def test_zero_dimension_account_stream_is_readable_despite_compiler_export_limitation(self):
        case = self.fixture['zero_dimension_native']
        self.assertEqual(predefined.read(base64.b64decode(case['raw']), 'ChartOfAccounts'), {'First': case['value']})

    def test_full_export_cannot_omit_nonempty_native_plan_assets(self):
        for case in self.fixture['cases']:
            source, _, _ = self.stage(case)
            record = dict(kind=case['kind'], path=case['folder']+'/'+case['name']+'.xml')
            filename = case['folder']+'/'+case['name']+'/Ext/Predefined.xml'
            with self.subTest(kind=case['kind']):
                with self.assertRaisesRegex(ValueError, 'omitted nonempty predefined data'):
                    ibcmd_backend.require_complete_export({k:v for k,v in source.image.items() if k==case['id']+predefined.FAMILIES[case['kind']][1]}, {case['id']: record}, {})
                ibcmd_backend.require_complete_export({k:v for k,v in source.image.items() if k==case['id']+predefined.FAMILIES[case['kind']][1]}, {case['id']: record}, {filename: b'present'})

    def test_missing_empty_predefined_asset_does_not_create_a_false_omission(self):
        case = next(row for row in self.fixture['cases'] if row['kind']=='ChartOfCharacteristicTypes')
        source, _, _ = self.stage(case)
        name = case['id']+'.7'; docs = s.Parser(source.image[name].decode('utf-8-sig')).documents()
        rows = docs[0][1][2]; root = rows[16][2]
        root[-2:] = [s.atom(0)]
        rows[-1] = s.atom(0)
        source.image[name] = s.native_body_bytes(docs)
        self.assertEqual(predefined.read(source.image[name], case['kind']), {})
        ibcmd_backend.require_complete_export({k:v for k,v in source.image.items() if k==case['id']+predefined.FAMILIES[case['kind']][1]},
            {case['id']: dict(kind=case['kind'], path=case['folder']+'/'+case['name']+'.xml')}, {})


if __name__ == '__main__':
    unittest.main()
