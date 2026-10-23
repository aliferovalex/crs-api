"""All 13 native write/periodicity combinations and both form main types."""
import copy,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import metadata_context
import xml_namespaces
import native_metadata as s, managed_form_xml as forms, managed_form_operations as serializer
import managed_form_bindings as bindings
import metadata_object_xml as objects,native_collection_editor as collections
import object_change_serializer as changes
from test_managed_form_creation import store


class InformationRegisterModesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.witness=json.loads(Path(__file__).with_name('fixtures').joinpath('information_register_modes_851.json').read_text(encoding='utf-8'))

    def test_native_standard_field_presence_and_paths_for_all_modes(self):
        self.assertEqual(len(self.witness['cases']),13)
        for row in self.witness['cases']:
            owner=s.Parser(row['owner']).documents()[0];paths=forms.object_paths(owner,'InformationRegister')
            expected={name for name in row['paths'] if name in ('Period','Recorder','LineNumber','Active')}
            actual={name for name in ('Period','Recorder','LineNumber','Active') if 'Object.'+name in paths}
            with self.subTest(mode=row['mode'],period=row['period']):
                self.assertEqual(expected,actual)
                bound=bindings.retarget(paths,'Data',17,True)
                for name,value in row['paths'].items():self.assertEqual(s.render(bound['Data.'+name]),value)

    def test_native_main_attribute_rows_for_record_managers_and_sets(self):
        for label in ('cases','managers'):
            for row in self.witness[label]:
                owner=s.Parser(row['owner']).documents()[0]
                _,_,raw=serializer.create_native('InformationRegister',Path(row['form_path']).stem,'8.5.1.1529',owner,interface_xml=row['xml'])
                actual=forms.interface(raw);expected=forms.interface(row['native'].encode('utf-8'));count=int(s.val(actual[3][1]))
                with self.subTest(mode=row['mode'],period=row['period'],label=label):
                    self.assertEqual(s.render(actual[3][:2+count]),s.render(expected[3][:2+count]))

    def test_whole_owner_xml_serializes_both_mode_properties_like_native(self):
        for row in self.witness['cases']:
            text=collections.strip_xml(row['owner_xml'],'InformationRegister')
            oid,name,raw,_=objects.object_xml(text,'8.5.1.1529','InformationRegister')
            actual=s.Parser(raw.decode('utf-8-sig')).documents()[0];expected=s.Parser(row['owner']).documents()[0]
            expected[5]=[expected[5][0],s.atom(0)]
            with self.subTest(mode=row['mode'],period=row['period']):
                self.assertEqual(oid,row['owner_id']);self.assertEqual(name,row['name'])
                self.assertEqual(s.render(actual),s.render(expected))

    def test_unavailable_standard_fields_are_rejected(self):
        for row in self.witness['cases']:
            missing=set(('Period','Recorder','LineNumber','Active'))-set(row['fields'])
            for name in missing:
                root=E.fromstring(row['xml']);table=root.find(forms.Q+'ChildItems')[0]
                field=E.SubElement(table.find(forms.Q+'ChildItems'),forms.Q+'InputField',name='Missing'+name,id='900')
                E.SubElement(field,forms.Q+'DataPath').text='Data.'+name
                owner=s.Parser(row['owner']).documents()[0]
                with self.subTest(mode=row['mode'],period=row['period'],name=name),self.assertRaisesRegex(ValueError,'DataPath'):
                    serializer.create_native('InformationRegister','TestForm','8.5.1.1529',owner,interface_xml=E.tostring(root,encoding='unicode'))

    def test_existing_register_mode_changes_preserve_generated_types_and_children(self):
        fixture=json.loads(Path(__file__).with_name('fixtures').joinpath('native_register_collections_851.json').read_text(encoding='utf-8'))
        request=fixture['request'];context=metadata_context.context_objects(request['context']);oid=request['parent_id']
        source=s.Parser(fixture['owner_before']).documents()[0]
        source[1][23]=s.atom(0);source[7][2][0][1][19]=[s.atom('U',True)]
        q='{'+xml_namespaces.MD+'}';root=E.fromstring(request['object_xml']);children=root[0].find(q+'ChildObjects')
        for node in list(children):
            if node.tag in (q+'Form',q+'Template'):children.remove(node)
        for row in collections.inspect(source,'InformationRegister',context[oid][0],context):
            for child in row['ids']:E.SubElement(children,q+row['rule']['xml_name']).text=s.val(context[child][0][9])
        for case in self.witness['cases']:
            target=copy.deepcopy(root);props=target[0].find(q+'Properties')
            props.find(q+'InformationRegisterPeriodicity').text=case['period']
            props.find(q+'WriteMode').text=case['mode']
            r=dict(request,object_type='InformationRegister',object_id=oid,
                   snapshot=store(context[oid],s.native_body_bytes([source])),
                   object_xml=E.tostring(target,encoding='unicode'))
            with self.subTest(mode=case['mode'],period=case['period']):
                _,raw,_,_=changes.serialize(r,native_content=True)
                actual=s.Parser(raw.decode('utf-8-sig')).documents()[0]
                expected=copy.deepcopy(source);witness=s.Parser(case['owner']).documents()[0]
                expected[1][18:20]=copy.deepcopy(witness[1][18:20])
                # The complete source XML deliberately changes the comment too.
                expected[1][15][1][4]=s.atom(props.find(q+'Comment').text or '',True)
                self.assertEqual(s.render(actual),s.render(expected))

    def test_unknown_native_modes_are_not_interpreted_as_valid(self):
        source=s.Parser(self.witness['cases'][0]['owner']).documents()[0]
        for slot in (18,19):
            owner=copy.deepcopy(source);owner[1][slot]=s.atom(99)
            with self.assertRaisesRegex(ValueError,'binding mode'):forms.object_paths(owner,'InformationRegister')


if __name__=='__main__':unittest.main()
