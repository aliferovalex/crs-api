"""Native CF/XML witnesses for every repository metadata form owner."""
import json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import managed_form_profiles as profiles
import managed_form_operations as serializer
import managed_form_xml as forms
import native_metadata as s
import form_definition_xml as definition
import metadata_structure as structure
from test_form_kinds_xml import common_xml


class AllFormOwnersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.witnesses=json.loads(Path(__file__).with_name('fixtures').joinpath('native_form_owners_851.json').read_text(encoding='utf-8-sig'))

    def test_every_schema_repository_form_owner_has_a_native_profile(self):
        expected={p['runtime_name'] for p in structure.classes().values() if p['class_id'] and any(r['xml_name']=='Form' for r in p['collections'])}
        self.assertEqual(expected,set(profiles.KINDS)-{'CommonForm'})
        self.assertEqual(expected,set(self.witnesses))

    def test_each_native_description_round_trips_without_changing_its_wrapper(self):
        for kind,w in self.witnesses.items():
            with self.subTest(kind=kind):
                raw=w['form'].encode('utf-8');converted=definition.convert(raw,w['definition'],kind,'8.5.1.1529')
                self.assertEqual(s.render(s.Parser(raw.decode()).documents()),s.render(s.Parser(converted.decode('utf-8-sig')).documents()))

    def test_whole_scalar_interface_and_module_work_for_every_owner(self):
        for kind,w in self.witnesses.items():
            with self.subTest(kind=kind):
                owner=s.Parser(w['owner']).documents()[0]
                fid,body,external=serializer.create_native(kind,'ProbeForm','8.5.1.1529',owner,w['definition'],common_xml(),'// complete module')
                common=profiles.common(s.Parser(body.decode('utf-8-sig')).documents()[0],kind)
                self.assertEqual(s.val(common[1][2]),fid)
                form=forms.interface(external);self.assertEqual(s.val(form[2]),'// complete module')
                self.assertEqual(s.val(form[3][1]),'1');self.assertEqual(s.val(form[3][2][3]),'Message')
                idx,count,end=forms.elements.form_collection(form);self.assertEqual(count,1)
                self.assertEqual(s.render(form[1][idx+2][11]),'{1,{1}}')

    def test_unmapped_main_attribute_binding_is_explicitly_rejected(self):
        kind='InformationRegister';w=self.witnesses[kind];owner=s.Parser(w['owner']).documents()[0]
        top=E.fromstring(common_xml());attr=top.find(forms.Q+'Attributes')[0];attr.append(E.Element(forms.Q+'MainAttribute'));attr[-1].text='true'
        with self.assertRaisesRegex(ValueError,'Main attribute binding'):
            serializer.create_native(kind,'ProbeForm','8.5.1.1529',owner,w['definition'],E.tostring(top,encoding='unicode'))

    def test_opaque_owner_does_not_ignore_changes_including_trailing_spaces(self):
        import metadata_owner_change
        kind='SettingsStorage';owner=s.Parser(self.witnesses[kind]['owner']).documents()[0];common=profiles.owner_common(owner,kind)
        oid=s.val(common[1][2]);name=s.val(common[2])
        before=('<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses"><SettingsStorage uuid="%s"><Properties><Name>%s</Name><Comment/><Unsupported>Value</Unsupported></Properties><ChildObjects/></SettingsStorage></MetaDataObject>')%(oid,name)
        for value in ('Changed','Value '):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'Unmapped owner properties'):
                metadata_owner_change.content(dict(object_type=kind,object_id=oid,before_xml=before,object_xml=before.replace('>Value<','>'+value+'<')))

    def test_child_only_fast_path_keeps_inline_metadata_in_the_comparison(self):
        import metadata_owner_change
        q='{http://v8.1c.ru/8.3/MDClasses}'
        for kind,profile in structure.classes().items():
            if profile['runtime_name'] not in profiles.owner_profiles():continue
            for rule in profile['collections']:
                if rule['storage']=='stored_name':continue
                top=E.Element(q+'MetaDataObject');owner=E.SubElement(top,q+profile['xml_name'])
                children=E.SubElement(owner,q+'ChildObjects');node=E.SubElement(children,q+rule['xml_name'],uuid='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee')
                E.SubElement(E.SubElement(node,q+'Properties'),q+'Name').text='Before'
                before=metadata_owner_change.retained_xml(top,profile['runtime_name'])
                node.find(q+'Properties/'+q+'Name').text='After'
                with self.subTest(kind=kind,collection=rule['xml_name']):
                    self.assertNotEqual(before,metadata_owner_change.retained_xml(top,profile['runtime_name']))


if __name__=='__main__':unittest.main()
