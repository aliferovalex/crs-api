"""Chart scalar mappings follow full independent native object bodies."""
import json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
import test_document_serializer
import metadata_object_xml as objects,metadata_common_xml as common,native_metadata as s


class ChartPropertyTests(unittest.TestCase):
    def samples(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('chart_properties_851.json').read_text(encoding='utf-8'))['samples']

    def test_all_native_bodies_and_inverse_xml_match(self):
        for row in self.samples():
            with self.subTest(case=row['label']):
                raw=objects.create(row['xml'],'8.5.1.1529','ChartOfAccounts')[2]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(row['body']).documents()))
                top=objects.export(s.Parser(row['body']).documents()[0],{},'8.5.1.1529','ChartOfAccounts')
                self.assertEqual(objects.create(E.tostring(top,encoding='unicode'),'8.5.1.1529','ChartOfAccounts')[2],raw)

    def test_whole_changes_preserve_all_fourteen_generated_ids(self):
        cases=self.samples();base=cases[0];source=s.Parser(base['body']).documents()[0];layout=objects.profiles.layout('ChartOfAccounts')
        for row in cases[1:]:
            top=E.fromstring(row['xml']);top[0].set('uuid',base['id']);top[0].remove(top[0].find(objects.Q+'InternalInfo'));top[0].find(objects.Q+'Properties/'+objects.Q+'Name').text=base['name']
            for node in top.iter():
                if node.text:node.text=node.text.replace('ChartOfAccounts.'+row['name']+'.','ChartOfAccounts.'+base['name']+'.')
            raw,_=objects.change(E.tostring(top,encoding='unicode'),'8.5.1.1529','ChartOfAccounts',source);expected=s.Parser(row['body']).documents()[0];common_node=objects.at(expected,objects.common_path(layout));common_node[1][2]=s.atom(base['id']);common_node[2]=s.atom(base['name'],True)
            for slot in layout['generated_slots']:expected[1][slot]=source[1][slot]
            self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()[0]),s.render(expected))

    def test_literal_string_codec_is_not_a_finite_set_of_masks(self):
        rule=objects.profiles.layout('ChartOfAccounts')['scalar_properties']['CodeMask']
        for text in ('','##/##/###','Код "А"\r\nзначение'):
            value=common.scalar_value(text,rule);native=s.Parser(s.render(s.atom(value,True))).documents()[0]
            self.assertEqual(common.scalar_text(native,rule),text)
        with self.assertRaises(ValueError):common.scalar_value('bad\0mask',rule)
        with self.assertRaises(ValueError):common.scalar_text(s.atom(1),rule)

    def test_invalid_values_and_references_to_disabled_fields_reject(self):
        base=self.samples()[0]
        for key,value in [('CodeSeries','Unknown'),('EditType','Unknown'),('CodeLength','-1'),('DescriptionLength','0'),('OrderLength','1.5'),('DataHistory','Unknown')]:
            top=E.fromstring(base['xml']);top[0].find(objects.Q+'Properties/'+objects.Q+key).text=value
            with self.subTest(property=key),self.assertRaises(ValueError):objects.create(E.tostring(top,encoding='unicode'),'8.5.1.1529','ChartOfAccounts')
