"""Verified command wrappers share converters across additional metadata owners."""
import copy,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import inline_command_xml as commands
import metadata_object_xml as objects
import metadata_targets
import inline_object_xml as inline
import native_metadata as s
import inline_metadata_xml as inline_metadata


class MoreCommandOwnerTests(unittest.TestCase):
    def data(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('more_command_owners_851.json').read_text(encoding='utf-8'))

    def test_complete_owner_bodies_match_independent_native_compilation(self):
        data=self.data()
        for case in data['cases']:
            with self.subTest(kind=case['kind']):
                index=metadata_targets.Index(metadata_targets.Target(**row) for row in case['references'])
                _,_,raw,_=objects.create(case['xml'],'8.5.1.1529',case['kind'],case['forms'],objects=index,templates=case['templates'],type_references=data['type_references'])
                self.assertEqual(raw.decode('utf-8-sig'),case['body'])

    def test_commands_round_trip_and_participate_in_owner_features(self):
        data=self.data()
        for case in data['cases']:
            with self.subTest(kind=case['kind']):
                profile=objects.profiles.layout(case['kind']);rule=profile['command_collections']['Command'];body=s.Parser(case['body']).documents()[0]
                entry=body[rule['slot']][2];xml=inline_metadata.export(entry,rule,type_references=data['type_references'])
                self.assertEqual(s.render(inline_metadata.read(xml,rule,type_references=data['type_references'])[2]),s.render(entry))
                self.assertIn(case['command_id'],inline.features(body,profile));self.assertEqual(commands.streams(body,profile),{case['command_id']:case['command_id']+'.2'})

    def test_enum_values_forms_templates_and_commands_export_together(self):
        data=self.data();case=next(row for row in data['cases'] if row['kind']=='Enum');body=s.Parser(case['body']).documents()[0]
        references=metadata_targets.Index(metadata_targets.Target(**row) for row in case['references']);name=E.fromstring(case['xml'])[0].findtext(objects.Q+'Properties/'+objects.Q+'Name')
        index=metadata_targets.creation('Enum',case['id'],name,case['forms'],references,templates=case['templates'])
        top=objects.export(body,case['forms'],'8.5.1.1529','Enum',objects=index,type_references=data['type_references'])
        for kind in ('EnumValue','Form','Template','Command'):self.assertEqual(len(top.findall('.//'+objects.Q+kind)),len(E.fromstring(case['xml']).findall('.//'+objects.Q+kind)))
        self.assertEqual(objects.create(E.tostring(top,encoding='unicode'),'8.5.1.1529','Enum',case['forms'],objects=references,templates=case['templates'],type_references=data['type_references'])[2].decode('utf-8-sig'),case['body'])

    def test_enum_value_uuid_cannot_collide_with_a_command(self):
        data=self.data();case=next(row for row in data['cases'] if row['kind']=='Enum');top=E.fromstring(case['xml']);top.find('.//'+objects.Q+'EnumValue').set('uuid',case['command_id'])
        references=metadata_targets.Index(metadata_targets.Target(**row) for row in case['references'])
        with self.assertRaisesRegex(ValueError,'Duplicate EnumValue UUID'):objects.create(E.tostring(top,encoding='unicode'),'8.5.1.1529','Enum',case['forms'],objects=references,templates=case['templates'],type_references=data['type_references'])


if __name__=='__main__':unittest.main()
