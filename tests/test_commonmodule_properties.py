"""Common-module flags and reuse modes follow independent native variants."""
import base64
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree as E
import test_commonmodule_change as changes
import metadata_object_xml as objects
import metadata_context
import native_metadata as s
import commonmodule_serializer as modules
from test_managed_form_creation import store


class CommonModulePropertiesTests(unittest.TestCase):
    def samples(self):
        return json.loads(Path(__file__).with_name('fixtures').joinpath('common_module_flags_851.json').read_text(encoding='utf-8'))['samples']

    def test_all_independent_flag_and_reuse_variants_roundtrip(self):
        for case in self.samples():
            with self.subTest(name=case['name']):
                raw=objects.create(case['xml'],'8.5.1.1529','CommonModule')[2]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))
                xml=objects.export(s.Parser(case['body']).documents()[0],{},'8.5.1.1529','CommonModule')
                self.assertEqual(objects.create(E.tostring(xml,encoding='unicode'),'8.5.1.1529','CommonModule')[2],raw)

    def test_text_only_change_preserves_all_flags_and_full_xml_changes_them(self):
        cases=self.samples()
        for index,case in enumerate(cases):
            request=changes.fixture();docs=metadata_context.context_objects(request['context'])[request['object_id']];docs[2]=[s.atom(0)];body=s.Parser(case['body']).documents()[0]
            common=body[1][1];common[1][2]=s.atom(request['object_id']);common[2]=docs[0][9]
            request['snapshot']=store(docs,s.native_body_bytes([body]))
            with self.subTest(source=case['name']):
                actual=s.Parser(modules.compile_change(request).body.decode('utf-8-sig')).documents()[0]
                self.assertEqual(s.render(actual),s.render(body))
                next_case=cases[(index+1)%len(cases)];root=E.fromstring(next_case['xml']);root[0].set('uuid',request['object_id']);root[0].find(objects.Q+'Properties/'+objects.Q+'Name').text=s.val(docs[0][9]);request['object_xml']=E.tostring(root,encoding='unicode')
                changed=s.Parser(modules.compile_change(request).body.decode('utf-8-sig')).documents()[0]
                expected=s.Parser(next_case['body']).documents()[0]
                self.assertEqual(s.render(changed[1][2:]),s.render(expected[1][2:]))

    def test_unknown_flag_and_reuse_values_reject(self):
        case=self.samples()[0]
        for key in objects.profiles.layout('CommonModule')['scalar_properties']:
            root=E.fromstring(case['xml']);root[0].find(objects.Q+'Properties/'+objects.Q+key).text='unknown'
            with self.subTest(property=key),self.assertRaisesRegex(ValueError,'property value'):
                objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','CommonModule')
