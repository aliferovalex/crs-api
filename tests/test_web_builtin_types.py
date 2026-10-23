"""Whole WebService bodies for independently compiled XML Schema type names."""
import json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import metadata_object_xml as objects
import native_metadata as s
import xml_namespaces


class WebBuiltinTypeTests(unittest.TestCase):
    def fixture(self):
        return json.loads(Path(__file__).with_name('fixtures').joinpath('web_builtin_types_851.json').read_text(encoding='utf-8'))

    def test_all_builtin_return_and_parameter_types_match_native_complete_body(self):
        case=self.fixture();_,_,raw,features=objects.create(case['xml'],'8.5.1.1529','WebService')
        self.assertEqual(raw.decode('utf-8-sig'),case['body']);self.assertEqual(len(case['types']),46);self.assertEqual(len(features),92)
        body=s.Parser(case['body']).documents()[0]
        for name,row in zip(case['types'],body[3][2:]):
            with self.subTest(name=name):
                self.assertEqual(s.val(row[0][2][2]),name);self.assertEqual(s.render(row[0][2]),s.render(row[2][2][0][2]))
        self.assertEqual(objects.change(case['xml'],'8.5.1.1529','WebService',body)[0],raw)
        top=objects.export(body,{},'8.5.1.1529','WebService')
        self.assertEqual(objects.create(E.tostring(top,encoding='unicode'),'8.5.1.1529','WebService')[2],raw)

    def test_prefix_is_resolved_by_namespace_not_literal_spelling(self):
        case=self.fixture();xml=case['xml'].replace('xmlns:xs=','xmlns:builtin=').replace('>xs:','>builtin:')
        self.assertEqual(objects.create(xml,'8.5.1.1529','WebService')[2].decode('utf-8-sig'),case['body'])

    def test_unknown_type_and_namespace_are_rejected_for_both_properties(self):
        case=self.fixture()
        for tag in ('XDTOReturningValueType','XDTOValueType'):
            for value in ('xs:Typo','missing:string','xs:string:extra',''):
                top=E.fromstring(case['xml']);top.find('.//'+objects.Q+tag).text=value
                with self.subTest(tag=tag,value=value),self.assertRaises(ValueError):
                    objects.create(xml_namespaces.render(top,case['xml']),'8.5.1.1529','WebService')


if __name__=='__main__':unittest.main()
