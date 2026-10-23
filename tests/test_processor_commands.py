"""Inline command bodies match native owner profiles and round-trip whole XML."""
import copy,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import native_metadata as s
import inline_metadata_xml as inline_metadata
import metadata_object_xml as objects
import metadata_targets
import inline_command_xml as commands
import object_xml_profiles as profiles
import configuration_export as export


class ProcessorCommandTests(unittest.TestCase):
    def cases(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('processor_commands_851.json').read_text(encoding='utf-8'))['cases']

    def test_creation_and_full_export_match_independent_native_compilation(self):
        for case in self.cases():
            with self.subTest(kind=case['kind']):
                oid,name,raw,_=objects.create(case['xml'],'8.5.1.1529',case['kind'],case['forms'],templates=case['templates'])
                self.assertEqual(raw.decode('utf-8-sig'),case['body'])
                source=s.Parser(case['body']).documents()[0];index=metadata_targets.creation(case['kind'],oid,name,case['forms'],templates=case['templates'])
                xml=objects.export(source,case['forms'],'8.5.1.1529',case['kind'],objects=index)
                rebuilt=objects.create(E.tostring(xml,encoding='unicode'),'8.5.1.1529',case['kind'],case['forms'],templates=case['templates'])[2]
                self.assertEqual(rebuilt,raw)
                self.assertEqual(commands.streams(source,profiles.layout(case['kind'])),{case['command_id']:case['command_id']+'.2'})

    def test_command_edit_uses_whole_xml_and_preserves_other_native_collections(self):
        for case in self.cases():
            top=E.fromstring(case['xml']);top.find('.//'+objects.Q+'Command/'+objects.Q+'Properties/'+objects.Q+'Comment').text='Changed command'
            source=s.Parser(case['body']).documents()[0];oid=case['id'];name=top[0].findtext(objects.Q+'Properties/'+objects.Q+'Name')
            index=metadata_targets.creation(case['kind'],oid,name,case['forms'],templates=case['templates'])
            raw,features=objects.change(E.tostring(top,encoding='unicode'),'8.5.1.1529',case['kind'],source,objects=index,reference_objects=index)
            actual=s.Parser(raw.decode('utf-8-sig')).documents()[0];slot=profiles.layout(case['kind'])['command_collections']['Command']['slot']
            self.assertIn(case['command_id'],features);self.assertNotEqual(s.render(source[slot]),s.render(actual[slot]))
            self.assertEqual([s.render(v) for i,v in enumerate(actual) if i!=slot],[s.render(v) for i,v in enumerate(source) if i!=slot])

    def test_command_export_rejects_unmapped_native_properties(self):
        for case in self.cases():
            profile=profiles.layout(case['kind'])['command_collections']['Command'];source=s.Parser(case['body']).documents()[0];entry=copy.deepcopy(source[profile['slot']][2])
            inline_metadata.at(entry,profile['common_path'])[-1]=s.atom(123)
            with self.subTest(kind=case['kind']),self.assertRaisesRegex(ValueError,'outside the verified'):inline_metadata.export(entry,profile)

    def test_companion_requires_a_declared_command_and_a_verified_owner(self):
        for case in self.cases():
            record=dict(kind=case['kind'],path=case['path'],node=E.fromstring(case['xml'])[0])
            prefix=str(Path(case['path']).with_suffix('')).replace('\\','/')+'/'
            self.assertTrue(export.supported_companion(record,prefix+'Commands/CRSRun/Ext/CommandModule.bsl',{}))
            self.assertFalse(export.supported_companion(record,prefix+'Commands/Unknown/Ext/CommandModule.bsl',{}))


if __name__=='__main__':unittest.main()
