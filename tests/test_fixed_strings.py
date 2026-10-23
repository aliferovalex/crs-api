"""Fixed string qualifiers verified against independent Configurator bodies."""
import copy,json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
import test_document_serializer
import metadata_object_xml as objects,native_metadata as s,type_description_xml as types


class FixedStringTests(unittest.TestCase):
    def samples(self):
        return json.loads(Path(__file__).with_name('fixtures').joinpath('fixed_strings_851.json').read_text(encoding='utf-8'))['samples']

    def test_native_complete_objects_and_inverse_match(self):
        for row in self.samples():
            with self.subTest(case=row['label']):
                raw=objects.create(row['xml'],'8.5.1.1529',row['kind'])[2]
                expected=s.Parser(row['body']).documents()
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(expected))
                top=objects.export(expected[0],{},'8.5.1.1529',row['kind'])
                self.assertEqual(objects.create(E.tostring(top,encoding='unicode'),'8.5.1.1529',row['kind'])[2],raw)
                self.assertEqual(s.render(types.read(E.fromstring(row['xml']).find('.//'+objects.Q+'Type'))),'{"Pattern",{"S",%d,0}}'%row['length'])

    def test_full_xml_switches_length_modes_without_replacing_identities(self):
        row=self.samples()[0];source=s.Parser(row['body']).documents()[0]
        root=E.fromstring(row['xml']);qualifiers=root.find('.//'+types.Q+'StringQualifiers')
        qualifiers.find(types.Q+'Length').text='64';qualifiers.find(types.Q+'AllowedLength').text='Variable'
        raw,_=objects.change(E.tostring(root,encoding='unicode'),'8.5.1.1529',row['kind'],source)
        body=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.render(body[8][2][0][1][1][2]),'{"Pattern",{"S",64,1}}')
        expected=copy.deepcopy(source);expected[8][2][0][1][1][2]=s.Parser('{"Pattern",{"S",64,1}}').documents()[0]
        self.assertEqual(s.render(body),s.render(expected))

    def test_invalid_fixed_qualifiers_are_rejected_in_both_directions(self):
        for length in (-1,0,101,1024):
            with self.subTest(length=length):
                node=E.fromstring(self.samples()[0]['xml']).find('.//'+objects.Q+'Type')
                node.find(types.Q+'StringQualifiers/'+types.Q+'Length').text=str(length)
                with self.assertRaises(ValueError):types.read(node)
                with self.assertRaises(ValueError):types.export(s.Parser('{"Pattern",{"S",%d,0}}'%length).documents()[0],objects.Q+'Type')

    def test_shared_scalar_and_composite_readers_keep_fixed_qualifier(self):
        for row in self.samples():
            node=E.fromstring(row['xml']).find('.//'+objects.Q+'Type')
            pattern='{"Pattern",{"S",%d,0}}'%row['length']
            self.assertEqual(s.render(types.read_form(node)),pattern)
            self.assertEqual(s.render(types.read_metadata(node)),pattern)
            E.SubElement(node,types.Q+'Type').text='xs:boolean'
            expected='{"Pattern",{"B"},{"S",%d,0}}'%row['length']
            self.assertEqual(s.render(types.read_form(node)),expected)
            self.assertEqual(s.render(types.read_metadata(types.export_metadata(s.Parser(expected).documents()[0],objects.Q+'Type'))),expected)
