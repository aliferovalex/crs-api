"""Complete document search/lock lists use independent native witnesses."""
import copy,json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
import test_document_serializer
import metadata_object_xml as objects
import native_metadata as s
import managed_form_xml as forms


class DocumentFieldListTests(unittest.TestCase):
    def samples(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('document_field_lists_851.json').read_text(encoding='utf-8'))['samples']

    def test_independent_full_bodies_and_inverse_match(self):
        for case in self.samples():
            with self.subTest(case=case['label']):
                raw=objects.create(case['xml'],'8.5.1.1529','Document')[2]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))
                xml=objects.export(s.Parser(case['body']).documents()[0],{},'8.5.1.1529','Document')
                self.assertEqual(objects.create(E.tostring(xml,encoding='unicode'),'8.5.1.1529','Document')[2],raw)

    def test_whole_changes_keep_ids_and_complete_ordered_lists(self):
        cases=self.samples();base=cases[0];source=s.Parser(base['body']).documents()[0];layout=objects.profiles.layout('Document')
        for case in cases[1:]:
            root=E.fromstring(case['xml']);root[0].set('uuid',base['id']);root[0].remove(root[0].find(objects.Q+'InternalInfo'));root[0].find(objects.Q+'Properties/'+objects.Q+'Name').text=base['name'];root[0].find(objects.Q+'ChildObjects/'+objects.Q+'Attribute').set('uuid',base['attribute_id'])
            for node in root.iter():
                if node.text:node.text=node.text.replace('Document.'+case['name']+'.','Document.'+base['name']+'.')
            with self.subTest(case=case['label']):
                raw,_=objects.change(E.tostring(root,encoding='unicode'),'8.5.1.1529','Document',source)
                expected=s.Parser(case['body'].replace(case['id'],base['id']).replace(case['attribute_id'],base['attribute_id'])).documents()[0];common=objects.at(expected,objects.common_path(layout));common[2]=s.atom(base['name'],True)
                for slot in layout['generated_slots']:expected[1][slot]=source[1][slot]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()[0]),s.render(expected))

    def test_date_is_valid_for_locks_but_rejected_for_search_both_directions(self):
        cases={row['label']:row for row in self.samples()};root=E.fromstring(cases['DateLocks']['xml']);locks=root[0].find(objects.Q+'Properties/'+objects.Q+'DataLockFields');search=root[0].find(objects.Q+'Properties/'+objects.Q+'InputByString');search.clear();search.append(copy.deepcopy(locks[0]))
        with self.assertRaisesRegex(ValueError,'metadata field reference'):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','Document')
        native=s.Parser(cases['DateLocks']['body']).documents()[0];native[1][29][1]=copy.deepcopy(native[1][47][1])
        with self.assertRaisesRegex(ValueError,'native metadata field'):objects.export(native,{},'8.5.1.1529','Document')

    def test_zero_length_number_is_absent_from_lists_and_form_context(self):
        case=next(row for row in self.samples() if row['label']=='NoNumber');paths=forms.object_paths(s.Parser(case['body']).documents()[0],'Document')
        self.assertNotIn('Object.Number',paths);self.assertEqual(paths.types['Object.Date'],'D');self.assertIn('Object.SearchKey',paths)
        root=E.fromstring(case['xml']);node=root[0].find(objects.Q+'Properties/'+objects.Q+'InputByString');E.SubElement(node,'{http://v8.1c.ru/8.3/xcf/readable}Field').text='Document.'+case['name']+'.StandardAttribute.Number'
        with self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','Document')

    def test_search_rejects_unindexed_attributes(self):
        case=next(row for row in self.samples() if row['label']=='Attribute');root=E.fromstring(case['xml']);root[0].find(objects.Q+'ChildObjects/'+objects.Q+'Attribute/'+objects.Q+'Properties/'+objects.Q+'Indexing').text='DontIndex'
        with self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','Document')
        native=s.Parser(case['body']).documents()[0];native[5][2][0][2]=s.atom(0)
        with self.assertRaises(ValueError):objects.export(native,{},'8.5.1.1529','Document')

    def test_foreign_missing_and_duplicate_fields_reject(self):
        case=self.samples()[0]
        for value in ('Document.Other.StandardAttribute.Number','Document.'+case['name']+'.Attribute.Missing'):
            root=E.fromstring(case['xml']);root[0].find(objects.Q+'Properties/'+objects.Q+'InputByString')[0].text=value
            with self.subTest(field=value),self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','Document')
        root=E.fromstring(case['xml']);node=root[0].find(objects.Q+'Properties/'+objects.Q+'InputByString');node.append(copy.deepcopy(node[0]))
        with self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','Document')

    def test_omitted_list_cannot_preserve_a_disabled_template_field(self):
        case=next(row for row in self.samples() if row['label']=='NoNumber');root=E.fromstring(case['xml']);props=root[0].find(objects.Q+'Properties');props.remove(props.find(objects.Q+'InputByString'))
        # The independent Configurator probe rejects this same omitted-list XML.
        with self.assertRaisesRegex(ValueError,'Invalid default metadata field list: InputByString'):
            objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','Document')

    def test_omitted_valid_lists_retain_native_defaults(self):
        case=self.samples()[0];root=E.fromstring(case['xml']);props=root[0].find(objects.Q+'Properties')
        for key in ('InputByString','DataLockFields'):props.remove(props.find(objects.Q+key))
        raw=objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','Document')[2]
        self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))
