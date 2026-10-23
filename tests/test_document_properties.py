"""Document scalar mappings follow full independent Configurator bodies."""
import copy
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree as E
import test_document_serializer
import metadata_object_xml as objects
import native_metadata as s
import managed_form_xml as forms


class DocumentPropertyTests(unittest.TestCase):
    def samples(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('document_properties_851.json').read_text(encoding='utf-8'))['samples']

    def test_independent_full_bodies_and_reverse_xml_match(self):
        for case in self.samples():
            with self.subTest(case=case['label']):
                raw=objects.create(case['xml'],'8.5.1.1529','Document')[2]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))
                xml=objects.export(s.Parser(case['body']).documents()[0],{},'8.5.1.1529','Document')
                self.assertEqual(objects.create(E.tostring(xml,encoding='unicode'),'8.5.1.1529','Document')[2],raw)

    def test_whole_object_changes_preserve_generated_types(self):
        cases=self.samples();base=cases[0];source=s.Parser(base['body']).documents()[0];layout=objects.profiles.layout('Document')
        for case in cases[1:]:
            root=E.fromstring(case['xml']);root[0].set('uuid',base['id']);root[0].remove(root[0].find(objects.Q+'InternalInfo'));root[0].find(objects.Q+'Properties/'+objects.Q+'Name').text=base['name']
            for node in root.iter():
                if node.text:node.text=node.text.replace('Document.'+case['name']+'.','Document.'+base['name']+'.')
            with self.subTest(case=case['label']):
                raw,_=objects.change(E.tostring(root,encoding='unicode'),'8.5.1.1529','Document',source)
                expected=s.Parser(case['body']).documents()[0];common=objects.at(expected,objects.common_path(layout));common[1][2]=s.atom(base['id']);common[2]=s.atom(base['name'],True)
                for slot in layout['generated_slots']:expected[1][slot]=source[1][slot]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()[0]),s.render(expected))

    def test_numeric_number_uses_shared_form_binding_profile(self):
        cases={row['label']:row for row in self.samples()}
        for label,typ in [('Default','S'),('NumberTypeNumber','N')]:
            paths=forms.object_paths(s.Parser(cases[label]['body']).documents()[0],'Document')
            self.assertEqual(paths.types['Object.Number'],typ);self.assertEqual(paths.types['Object.Date'],'D')
            self.assertEqual(s.render(paths['Object.Number']),'{2,{1},{-2}}')

    def test_unknown_enums_and_invalid_number_lengths_are_rejected(self):
        for key,value in [('NumberType','Unknown'),('Posting','Unknown'),('NumberLength','-1'),('NumberLength','1.5'),('CheckUnique','yes')]:
            root=E.fromstring(self.samples()[0]['xml']);root[0].find(objects.Q+'Properties/'+objects.Q+key).text=value
            with self.subTest(property=key),self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','Document')

    def test_whole_form_conversion_matches_both_native_number_types(self):
        from test_defined_type_forms import signature
        cases=json.loads(Path(__file__).with_name('fixtures').joinpath('document_properties_851.json').read_text(encoding='utf-8'))['forms']
        for case in cases:
            owner=s.Parser(case['owner_body']).documents()[0];paths=forms.object_paths(owner,'Document')
            raw=forms.convert(cases[0]['interface'].encode('utf-8-sig'),case['xml'],paths=paths,object_name=case['owner'],kind='Document')
            self.assertEqual(signature(s.Parser(raw.decode('utf-8-sig')).documents()),signature(s.Parser(case['interface']).documents()))
