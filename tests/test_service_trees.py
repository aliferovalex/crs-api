"""Recursive inline service metadata shares the profiled command property codec."""
import json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import metadata_object_xml as objects
import inline_object_xml as features
import native_metadata as s
import xml_namespaces


class ServiceTreeTests(unittest.TestCase):
    def cases(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('service_trees_851.json').read_text(encoding='utf-8'))['cases']

    def test_complete_bodies_features_and_export_match_independent_compilation(self):
        for case in self.cases():
            with self.subTest(kind=case['kind']):
                _,_,raw,ids=objects.create(case['xml'],'8.5.1.1529',case['kind']);self.assertEqual(raw.decode('utf-8-sig'),case['body']);self.assertEqual(set(ids),set(case['features']))
                body=s.Parser(case['body']).documents()[0];self.assertEqual(set(features.features(body,objects.profiles.layout(case['kind']))),set(ids))
                top=objects.export(body,{},'8.5.1.1529',case['kind']);self.assertEqual(objects.create(E.tostring(top,encoding='unicode'),'8.5.1.1529',case['kind'])[2],raw)

    def test_complete_target_xml_deletes_nested_methods_and_parameters(self):
        for case in self.cases():
            top=E.fromstring(case['xml']);children=top[0].find(objects.Q+'ChildObjects');source=s.Parser(case['body']).documents()[0]
            if case['kind']=='HTTPService':
                nested=children[0].find(objects.Q+'ChildObjects');removed=nested[0].get('uuid');nested.remove(nested[0])
            else:
                removed=children[0].find(objects.Q+'ChildObjects')[0].get('uuid');children[0].find(objects.Q+'ChildObjects').clear()
            raw,ids=objects.change(xml_namespaces.render(top,case['xml']),'8.5.1.1529',case['kind'],source)
            self.assertNotIn(removed,ids);self.assertEqual(set(ids),set(case['features'])-{removed})

    def test_duplicate_uuid_name_and_invalid_qname_are_rejected(self):
        case=self.cases()[1]
        for mutation in ('uuid','name','namespace'):
            top=E.fromstring(case['xml']);operations=top[0].find(objects.Q+'ChildObjects')
            if mutation=='uuid':operations[1].set('uuid',operations[0].get('uuid'))
            elif mutation=='name':operations[1].find(objects.Q+'Properties/'+objects.Q+'Name').text=operations[0].findtext(objects.Q+'Properties/'+objects.Q+'Name')
            else:operations[0].find(objects.Q+'Properties/'+objects.Q+'XDTOReturningValueType').text='unknown:string'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):objects.create(xml_namespaces.render(top,case['xml']),'8.5.1.1529',case['kind'])

    def test_existing_parameter_cannot_move_to_another_operation(self):
        case=self.cases()[1];top=E.fromstring(case['xml']);operations=top[0].find(objects.Q+'ChildObjects');first=operations[0].find(objects.Q+'ChildObjects');parameter=first[0];first.remove(parameter);operations[-1].find(objects.Q+'ChildObjects').append(parameter)
        with self.assertRaisesRegex(ValueError,'cannot move between collections'):objects.change(xml_namespaces.render(top,case['xml']),'8.5.1.1529',case['kind'],s.Parser(case['body']).documents()[0])


if __name__=='__main__':unittest.main()
