"""Complete catalogue property variants match independent native bodies."""
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree as E
import test_defined_types
import metadata_object_xml as objects
import managed_form_xml as forms
import native_metadata as s


class CatalogPropertyTests(unittest.TestCase):
    def samples(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('catalog_properties_851.json').read_text(encoding='utf-8'))['samples']

    def test_all_31_native_variants_roundtrip(self):
        for case in self.samples():
            with self.subTest(variant=case['label']):
                raw=objects.create(case['xml'],'8.5.1.1529','Catalog')[2]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))
                exported=objects.export(s.Parser(case['body']).documents()[0],{},'8.5.1.1529','Catalog')
                self.assertEqual(objects.create(E.tostring(exported,encoding='unicode'),'8.5.1.1529','Catalog')[2],raw)

    def test_whole_change_applies_each_property_and_preserves_generated_ids(self):
        cases=self.samples();index={case['label']:case for case in cases}
        for case in cases[1:]:
            baseline=index[case['baseline']];source=s.Parser(baseline['body']).documents()[0];root=E.fromstring(case['xml']);root[0].set('uuid',baseline['id']);root[0].remove(root[0].find(objects.Q+'InternalInfo'));root[0].find(objects.Q+'Properties/'+objects.Q+'Name').text=baseline['name']
            for node in root.iter():
                if node.text:node.text=node.text.replace('Catalog.'+case['name']+'.','Catalog.'+baseline['name']+'.')
            with self.subTest(variant=case['label']):
                raw,_=objects.change(E.tostring(root,encoding='unicode'),'8.5.1.1529','Catalog',source)
                actual=s.Parser(raw.decode('utf-8-sig')).documents()[0];expected=s.Parser(case['body']).documents()[0]
                common=objects.at(expected,objects.common_path(objects.profiles.layout('Catalog')));common[1][2]=s.atom(baseline['id']);common[2]=s.atom(baseline['name'],True)
                for slot in objects.profiles.layout('Catalog')['generated_slots']:expected[1][slot]=source[1][slot]
                self.assertEqual(s.render(actual),s.render(expected))

    def test_numeric_code_uses_shared_standard_field_binding_rules(self):
        cases={case['label']:case for case in self.samples()}
        for label,kind in [('Default','S'),('NumberCode','N')]:
            owner=s.Parser(cases[label]['body']).documents()[0];paths=forms.object_paths(owner,'Catalog')
            self.assertEqual(paths.types['Object.Code'],kind);self.assertEqual(paths.types['Object.Description'],'S')
            self.assertEqual(s.render(paths['Object.Code']),'{2,{1},{-2}}')

    def test_whole_form_conversion_matches_native_numeric_standard_code(self):
        from test_defined_type_forms import signature
        cases=json.loads(Path(__file__).with_name('fixtures').joinpath('catalog_properties_851.json').read_text(encoding='utf-8'))['forms']
        for case in cases:
            owner=s.Parser(case['owner_body']).documents()[0];paths=forms.object_paths(owner,'Catalog')
            raw=forms.convert(cases[0]['interface'].encode('utf-8-sig'),case['xml'],paths=paths,object_name=case['owner'],kind='Catalog')
            self.assertEqual(signature(s.Parser(raw.decode('utf-8-sig')).documents()),signature(s.Parser(case['interface']).documents()))

    def test_invalid_values_and_references_to_disabled_standard_fields_reject(self):
        case=self.samples()[0]
        for key,value in [('HierarchyType','Unknown'),('Hierarchical','yes'),('CodeLength','0'),('DescriptionLength','0'),('LevelCount','-1')]:
            root=E.fromstring(case['xml']);root[0].find(objects.Q+'Properties/'+objects.Q+key).text=value
            with self.subTest(property=key),self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','Catalog')
