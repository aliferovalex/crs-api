"""Chart field lists, inline attributes and main-form bindings share profiles."""
import copy,json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
import test_document_serializer
import metadata_object_xml as objects,native_metadata as s,managed_form_xml as forms


class ChartFieldListTests(unittest.TestCase):
    def samples(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('chart_field_lists_851.json').read_text(encoding='utf-8'))['samples']

    def test_all_complete_native_bodies_and_inverse_xml_match(self):
        for row in self.samples():
            with self.subTest(case=row['label']):
                raw=objects.create(row['xml'],'8.5.1.1529','ChartOfAccounts')[2];self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(row['body']).documents()))
                top=objects.export(s.Parser(row['body']).documents()[0],{},'8.5.1.1529','ChartOfAccounts');self.assertEqual(objects.create(E.tostring(top,encoding='unicode'),'8.5.1.1529','ChartOfAccounts')[2],raw)

    def test_whole_changes_retain_inline_and_generated_ids(self):
        cases=self.samples();base=cases[0];source=s.Parser(base['body']).documents()[0];layout=objects.profiles.layout('ChartOfAccounts')
        for row in cases[1:]:
            root=E.fromstring(row['xml']);root[0].set('uuid',base['id']);root[0].remove(root[0].find(objects.Q+'InternalInfo'));root[0].find(objects.Q+'Properties/'+objects.Q+'Name').text=base['name'];root[0].find(objects.Q+'ChildObjects/'+objects.Q+'Attribute').set('uuid',base['attribute_id'])
            for node in root.iter():
                if node.text:node.text=node.text.replace('ChartOfAccounts.'+row['name']+'.','ChartOfAccounts.'+base['name']+'.')
            raw,_=objects.change(E.tostring(root,encoding='unicode'),'8.5.1.1529','ChartOfAccounts',source);expected=s.Parser(row['body'].replace(row['id'],base['id']).replace(row['attribute_id'],base['attribute_id'])).documents()[0];objects.at(expected,objects.common_path(layout))[2]=s.atom(base['name'],True)
            for slot in layout['generated_slots']:expected[1][slot]=source[1][slot]
            self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()[0]),s.render(expected))

    def test_disabled_standard_fields_are_excluded_from_bindings(self):
        cases={row['label']:row for row in self.samples()}
        for label,missing in [('NoCode','Object.Code'),('NoDescription','Object.Description'),('Default','Object.Order')]:
            paths=forms.object_paths(s.Parser(cases[label]['body']).documents()[0],'ChartOfAccounts');self.assertNotIn(missing,paths);self.assertIn('Object.SearchKey',paths);self.assertEqual(paths.types['Object.DeletionMark'],'B')
        paths=forms.object_paths(s.Parser(cases['OrderLocks']['body']).documents()[0],'ChartOfAccounts');self.assertEqual(s.render(paths['Object.Order']),'{2,{1},{-17}}');self.assertEqual(paths.types['Object.Order'],'N')

    def test_foreign_duplicate_unindexed_or_disabled_references_reject(self):
        cases={row['label']:row for row in self.samples()}
        for label,value in [('Default','ChartOfAccounts.Missing.StandardAttribute.Code'),('NoCode','ChartOfAccounts.'+cases['NoCode']['name']+'.StandardAttribute.Code'),('Default','ChartOfAccounts.'+cases['Default']['name']+'.Attribute.SearchKey')]:
            row=cases[label];root=E.fromstring(row['xml']);root[0].find(objects.Q+'Properties/'+objects.Q+'InputByString')[0].text=value
            with self.subTest(case=label),self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','ChartOfAccounts')
        root=E.fromstring(cases['Default']['xml']);node=root[0].find(objects.Q+'Properties/'+objects.Q+'InputByString');node.append(copy.deepcopy(node[0]))
        with self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','ChartOfAccounts')

    def test_whole_main_forms_match_native_standard_and_inline_bindings(self):
        from test_defined_type_forms import signature
        import managed_form_operations as operations
        cases=json.loads(Path(__file__).with_name('fixtures').joinpath('chart_field_lists_851.json').read_text(encoding='utf-8'))['forms']
        for row in cases:
            paths=forms.object_paths(s.Parser(row['owner_body']).documents()[0],'ChartOfAccounts');raw=forms.convert(row['interface'].encode('utf-8-sig'),row['xml'],paths=paths,object_name=row['owner'],kind='ChartOfAccounts')
            self.assertEqual(signature(s.Parser(raw.decode('utf-8-sig')).documents()),signature(s.Parser(row['interface']).documents()))
            definition=E.Element(objects.Q+'MetaDataObject',version='2.21');form=E.SubElement(definition,objects.Q+'Form',uuid=row['id']);props=E.SubElement(form,objects.Q+'Properties')
            for key,value in [('Name','FieldsForm'),('Synonym',''),('Comment',''),('FormType','Managed')]:E.SubElement(props,objects.Q+key).text=value
            _,_,created=operations.create_native('ChartOfAccounts','FieldsForm','8.5.1.1529',s.Parser(row['owner_body']).documents()[0],E.tostring(definition,encoding='unicode'),row['xml'],'')
            self.assertEqual(signature(s.Parser(created.decode('utf-8-sig')).documents()),signature(s.Parser(row['interface']).documents()))

    def test_initial_import_nil_defaults_export_to_the_native_full_xml_canonical_form(self):
        import inline_attribute_xml as attributes
        cases=json.loads(Path(__file__).with_name('fixtures').joinpath('chart_field_lists_851.json').read_text(encoding='utf-8'))['raw_nil_variants']
        for row in cases:
            body=s.Parser(row['source_body']).documents()[0];original=s.render(body);self.assertEqual(s.render(body[7][2][0][1][19]),'{"S",""}')
            xml=objects.export(body,{},'8.5.1.1529','ChartOfAccounts');raw=objects.create(E.tostring(xml,encoding='unicode'),'8.5.1.1529','ChartOfAccounts')[2]
            self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(row['canonical_body']).documents()));self.assertEqual(s.render(body),original)
            bad=copy.deepcopy(body);bad[7][2][0][1][19]=[s.atom('N',True),s.atom(1)]
            with self.assertRaisesRegex(ValueError,'outside the verified XML profile'):objects.export(bad,{},'8.5.1.1529','ChartOfAccounts')
