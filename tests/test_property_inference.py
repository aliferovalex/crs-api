"""Candidate inference must use isolated native evidence and report ambiguity."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('property_inference',ROOT/'tools/infer_metadata_properties.py');tool=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(tool)


class PropertyInferenceTests(unittest.TestCase):
    def samples(self,name):return json.loads((ROOT/'tests/fixtures'/name).read_text(encoding='utf-8'))['samples']

    def test_independent_catalog_matrix_reproduces_reviewed_paths_and_values(self):
        result=tool.infer(self.samples('catalog_properties_851.json'),'Catalog');self.assertEqual(result['unresolved'],[])
        self.assertEqual(len(result['scalar_properties']),27)
        actual=tool.objects.profiles.layout('Catalog')['scalar_properties']
        for key,rule in result['scalar_properties'].items():
            self.assertEqual(rule['path'],actual[key]['path'])
            if 'values' in actual[key]:self.assertEqual(rule['values'],{label:actual[key]['values'][label] for label in rule['values']})

    def test_same_inference_handles_a_different_metadata_layout(self):
        samples=copy.deepcopy(self.samples('common_module_flags_851.json'))
        for row in samples:
            row['label']=row['name'];row['baseline']=None if row['name']=='ProbeDefault' else 'ProbeDefault'
            if row['name']=='ProbeServer':row['baseline']='ProbeClientOrdinaryApplication';row['overrides']={'Server':'false'}
        result=tool.infer(samples,'CommonModule');self.assertEqual(result['unresolved'],[])
        for key,rule in result['scalar_properties'].items():
            expected=tool.objects.profiles.layout('CommonModule')['scalar_properties'][key]
            self.assertEqual(rule['path'],expected['path']);self.assertEqual(rule['values'],expected['values'])
        self.assertEqual(len(result['scalar_properties']),8)

    def test_document_matrix_reproduces_reviewed_paths_and_values(self):
        result=tool.infer(self.samples('document_properties_851.json'),'Document')
        self.assertEqual(result['unresolved'],[]);self.assertEqual(len(result['scalar_properties']),22)
        actual=tool.objects.profiles.layout('Document')['scalar_properties']
        for key,rule in result['scalar_properties'].items():
            self.assertEqual(rule['path'],actual[key]['path'])
            if 'values' in actual[key]:self.assertEqual(rule['values'],actual[key]['values'])

    def test_numerator_xml_alias_is_supported_by_inference(self):
        rows=[row for row in self.samples('document_numerators_851.json') if row['kind']=='DocumentNumerators']
        result=tool.infer(rows,'DocumentNumerators');self.assertEqual(result['unresolved'],[]);self.assertEqual(len(result['scalar_properties']),5)
        actual=tool.objects.profiles.layout('DocumentNumerators')['scalar_properties']
        for key,rule in result['scalar_properties'].items():
            self.assertEqual(rule['path'],actual[key]['path'])
            if 'values' in actual[key]:self.assertEqual(rule['values'],actual[key]['values'])

    def test_chart_matrix_reproduces_reviewed_scalar_rules(self):
        result=tool.infer(self.samples('chart_properties_851.json'),'ChartOfAccounts');self.assertEqual(result['unresolved'],[]);self.assertEqual(len(result['scalar_properties']),22);actual=tool.objects.profiles.layout('ChartOfAccounts')['scalar_properties']
        for key,rule in result['scalar_properties'].items():
            self.assertEqual(rule['path'],actual[key]['path'])
            if 'values' in actual[key]:self.assertEqual(rule['values'],actual[key]['values'])
            if actual[key].get('string'):self.assertTrue(rule['quoted']);self.assertTrue(all(label==value for label,value in rule['values'].items()))

    def test_characteristic_alias_matrix_reproduces_twenty_three_properties(self):
        samples=[row for row in self.samples('characteristic_properties_851.json') if row.get('overrides') or row.get('baseline') is None]
        result=tool.infer(samples,'ChartOfCharacteristicType')
        self.assertEqual(result['unresolved'],[]);self.assertEqual(len(result['scalar_properties']),23)
        actual=tool.objects.profiles.layout('ChartOfCharacteristicType')['scalar_properties']
        for key,rule in result['scalar_properties'].items():
            self.assertEqual(rule['path'],actual[key]['path'])
            if 'values' in actual[key]:self.assertEqual(rule['values'],actual[key]['values'])

    def test_multiple_changes_are_reported_instead_of_selecting_a_slot(self):
        samples=copy.deepcopy(self.samples('catalog_properties_851.json')[:2]);body=tool.s.Parser(samples[1]['body']).documents()[0];body[1][14]=tool.s.atom(0);samples[1]['body']=tool.s.render(body)
        result=tool.infer(samples,'Catalog');self.assertEqual(result['scalar_properties'],{});self.assertEqual(len(result['unresolved']),1)

    def test_shared_native_slot_is_not_activated_for_two_properties(self):
        samples=copy.deepcopy(self.samples('catalog_properties_851.json'));base=samples[0];hierarchy=samples[1];other=next(row for row in samples if row['label']=='CheckUnique');body=tool.s.Parser(other['body']).documents()[0];body[1][14]=tool.s.atom(1);body[1][37]=tool.s.atom(1);other['body']=tool.s.render(body)
        result=tool.infer([base,hierarchy,other],'Catalog');self.assertEqual(result['scalar_properties'],{});self.assertEqual(result['unresolved'][0]['reason'],'shared_native_scalar')
