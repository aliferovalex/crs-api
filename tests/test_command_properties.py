"""Command properties use shared scalar/type/localized converters for each owner."""
import copy,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import inline_command_xml as commands
import metadata_object_xml as objects
import metadata_targets
import object_xml_profiles as profiles
import native_metadata as s
import inline_metadata_xml as inline_metadata


class CommandPropertyTests(unittest.TestCase):
    def cases(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('command_properties_851.json').read_text(encoding='utf-8'))['cases']

    def test_all_thirty_variants_match_independent_native_bodies_and_round_trip(self):
        for case in self.cases():
            with self.subTest(kind=case['kind']):
                refs=metadata_targets.Index(metadata_targets.Target(**row) for row in case['references'])
                oid,name,raw,_=objects.create(case['xml'],'8.5.1.1529',case['kind'],case['forms'],objects=refs,templates=case['templates'])
                self.assertEqual(raw.decode('utf-8-sig'),case['body'])
                source=s.Parser(case['body']).documents()[0];index=metadata_targets.creation(case['kind'],oid,name,case['forms'],refs,templates=case['templates'])
                exported=objects.export(source,case['forms'],'8.5.1.1529',case['kind'],objects=index)
                self.assertEqual(objects.create(E.tostring(exported,encoding='unicode'),'8.5.1.1529',case['kind'],case['forms'],objects=refs,templates=case['templates'])[2],raw)

    def test_clearing_properties_restores_profile_defaults(self):
        for case in self.cases():
            profile=profiles.layout(case['kind'])['command_collections']['Command'];top=E.fromstring(case['xml']);nodes=top.findall('.//'+inline_metadata.Q+'Command')
            for node in nodes:
                before=inline_metadata.read(node,profile)[2];exported=inline_metadata.export(before,profile);props=exported.find(inline_metadata.Q+'Properties')
                for key in ('ModifiesData','Representation','ParameterUseMode','ToolTip','CommandParameterType'):
                    props.remove(props.find(inline_metadata.Q+key))
                restored=inline_metadata.read(exported,profile)[2]
                for rule in profile['scalar_properties'].values():self.assertEqual(s.render(inline_metadata.at(restored,rule['path'])),s.render(inline_metadata.at(s.Parser(profile['template']).documents()[0],rule['path'])))
                self.assertEqual(s.render(inline_metadata.at(restored,profile['type_path'])),'{"Pattern"}')
                self.assertEqual(s.render(inline_metadata.at(restored,profile['localized_properties']['ToolTip'])),'{0}')

    def test_unknown_values_locales_and_reference_types_are_rejected(self):
        case=self.cases()[0];profile=profiles.layout(case['kind'])['command_collections']['Command'];node=E.fromstring(case['xml']).find('.//'+inline_metadata.Q+'Command')
        for key,value in [('ModifiesData','yes'),('Representation','Unknown'),('ParameterUseMode','Unknown')]:
            with self.subTest(key=key):
                changed=copy.deepcopy(node);changed.find(inline_metadata.Q+'Properties/'+inline_metadata.Q+key).text=value
                with self.assertRaisesRegex(ValueError,'Unsupported command property value'):inline_metadata.read(changed,profile)
        changed=copy.deepcopy(node);props=changed.find(inline_metadata.Q+'Properties');tip=props.find(inline_metadata.Q+'ToolTip');tip.set('unknown','true')
        with self.assertRaisesRegex(ValueError,'ToolTip'):inline_metadata.read(changed,profile)
        changed=copy.deepcopy(node);param=changed.find(inline_metadata.Q+'Properties/'+inline_metadata.Q+'CommandParameterType')
        E.SubElement(param,'{http://v8.1c.ru/8.1/data/core}Type').text='cfg:CatalogRef.Unknown'
        with self.assertRaises(ValueError):inline_metadata.read(changed,profile)

    def test_invalid_native_values_cannot_be_exported_as_defaults(self):
        case=self.cases()[0];profile=profiles.layout(case['kind'])['command_collections']['Command'];entry=inline_metadata.read(E.fromstring(case['xml']).find('.//'+inline_metadata.Q+'Command'),profile)[2]
        for path,value in [(profile['scalar_properties']['Representation']['path'],s.atom(99)),(profile['localized_properties']['ToolTip'],s.Parser('{2,"ru","one","ru","two"}').documents()[0]),(profile['type_path'],s.Parser('{"Pattern",{"#",aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa}}').documents()[0])]:
            changed=copy.deepcopy(entry);inline_metadata.at(changed,path[:-1])[path[-1]]=value
            with self.subTest(path=path),self.assertRaises(ValueError):inline_metadata.export(changed,profile)


if __name__=='__main__':unittest.main()
