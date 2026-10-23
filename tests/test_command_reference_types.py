"""Command parameter references reuse final metadata identities and dependencies."""
import json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import metadata_object_xml as objects
import metadata_targets
import metadata_type_references as refs
import native_metadata as s
import inline_metadata_xml as inline_metadata


class CommandReferenceTests(unittest.TestCase):
    def data(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('command_reference_types_851.json').read_text(encoding='utf-8'))

    def test_complete_native_bodies_and_export_match_independent_compilation(self):
        data=self.data()
        for case in data['cases']:
            with self.subTest(kind=case['kind']):
                index=metadata_targets.Index(metadata_targets.Target(**row) for row in case['references'])
                oid,name,raw,_=objects.create(case['xml'],'8.5.1.1529',case['kind'],case['forms'],objects=index,templates=case['templates'],type_references=data['type_references'])
                self.assertEqual(raw.decode('utf-8-sig'),case['body'])
                targets=metadata_targets.creation(case['kind'],oid,name,case['forms'],index,templates=case['templates'])
                exported=objects.export(s.Parser(case['body']).documents()[0],case['forms'],'8.5.1.1529',case['kind'],objects=targets,type_references=data['type_references'])
                self.assertEqual(refs.required(E.tostring(exported,encoding='unicode')),set(data['type_references']))
                result=objects.create(E.tostring(exported,encoding='unicode'),'8.5.1.1529',case['kind'],case['forms'],objects=index,templates=case['templates'],type_references=data['type_references'])[2]
                self.assertEqual(result,raw)

    def test_unresolved_reference_is_rejected_before_packet_assembly(self):
        data=self.data();case=data['cases'][0]
        import inline_command_xml as commands
        root=E.fromstring(case['xml']);node=next(n for n in root.findall('.//'+objects.Q+'Command') if n.findtext(objects.Q+'Properties/'+objects.Q+'Name')=='ProbeString')
        profile=objects.profiles.layout(case['kind'])['command_collections']['Command']
        with self.assertRaisesRegex(ValueError,'Unresolved'):inline_metadata.read(node,profile)
        entry=inline_metadata.read(node,profile,type_references=data['type_references'])[2]
        with self.assertRaisesRegex(ValueError,'Unresolved'):inline_metadata.export(entry,profile)


if __name__=='__main__':unittest.main()
