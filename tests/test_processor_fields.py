"""Processor and Report reuse verified inline/tabular converters and bindings."""
import copy,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import metadata_object_xml as objects
import metadata_targets
import managed_form_xml as forms
import native_metadata as s
import tabular_section_xml as tables


class ProcessorFieldTests(unittest.TestCase):
    def cases(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('processor_fields_851.json').read_text(encoding='utf-8'))['cases']

    def test_complete_native_bodies_match_independent_configurator_compilation(self):
        for case in self.cases():
            with self.subTest(kind=case['kind']):
                oid,name,raw,_=objects.create(case['xml'],'8.5.1.1529',case['kind'],case['forms'],templates=case['templates'])
                self.assertEqual(raw.decode('utf-8-sig'),case['body'])
                source=s.Parser(case['body']).documents()[0];index=metadata_targets.creation(case['kind'],oid,name,case['forms'],templates=case['templates'])
                exported=objects.export(source,case['forms'],'8.5.1.1529',case['kind'],objects=index)
                self.assertEqual(objects.create(E.tostring(exported,encoding='unicode'),'8.5.1.1529',case['kind'],case['forms'],templates=case['templates'])[2],raw)

    def test_forms_share_attribute_and_tabular_paths_from_the_native_owner(self):
        for case in self.cases():
            body=s.Parser(case['body']).documents()[0];paths=forms.object_paths(body,case['kind'])
            self.assertEqual(paths.types['Object.Text'],'S');self.assertEqual(paths.types['Object.Flag'],'B')
            self.assertIn('Object.Rows',paths.tables);self.assertEqual(paths.types['Object.Rows.Quantity'],'N')

    def test_inline_property_mask_does_not_accept_catalog_only_properties(self):
        for case in self.cases():
            top=E.fromstring(case['xml']);props=top[0].find(objects.Q+'ChildObjects/'+objects.Q+'Attribute/'+objects.Q+'Properties');E.SubElement(props,objects.Q+'Indexing').text='DontIndex'
            with self.subTest(kind=case['kind']),self.assertRaisesRegex(ValueError,'outside its owner profile'):objects.create(E.tostring(top,encoding='unicode'),'8.5.1.1529',case['kind'],case['forms'],templates=case['templates'])

    def test_nested_collection_guids_are_specific_to_the_owner(self):
        self.assertNotEqual(tables.layout('DataProcessor')['attribute_collection_id'],tables.layout('Report')['attribute_collection_id'])
        for case in self.cases():
            source=s.Parser(case['body']).documents()[0];row=tables.collection(source,case['kind'])[0]
            self.assertEqual(len(tables.attributes(row)),2);self.assertEqual(s.val(tables.common(row)[2]),'Rows')


if __name__=='__main__':unittest.main()
