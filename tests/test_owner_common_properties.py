"""Common-field edits preserve opaque bodies from all native owner witnesses."""
import copy,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import metadata_common_xml as common
import managed_form_profiles as profiles
import native_metadata as s
import metadata_owner_change


class OwnerCommonPropertiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=json.loads(Path(__file__).with_name('fixtures').joinpath('owned_form_properties_851.json').read_text(encoding='utf-8'))['owners']

    def test_each_native_owner_retains_every_byte_when_common_fields_are_unchanged(self):
        for row in self.rows:
            with self.subTest(kind=row['kind']):
                root=E.fromstring(row['xml']);raw=row['owner'].encode('utf-8')
                actual,name=common.patch(raw,profiles.owner_profiles()[row['kind']]['owner_common_path'],root,root,row['owner_id'])
                self.assertEqual(actual,raw)
                self.assertEqual(name,root[0].findtext(common.Q+'Properties/'+common.Q+'Name'))

    def test_combined_rename_synonym_and_comment_preserve_opaque_body_and_bom(self):
        for row in self.rows:
            with self.subTest(kind=row['kind']):
                before=E.fromstring(row['xml']);after=copy.deepcopy(before);props=after[0].find(common.Q+'Properties')
                props.find(common.Q+'Name').text='Renamed'+row['kind']
                props.find(common.Q+'Comment').text='Whole comment: "quoted"\nНовая строка'
                synonym=props.find(common.Q+'Synonym');synonym.clear()
                item=E.SubElement(synonym,common.localized.CORE+'item')
                E.SubElement(item,common.localized.CORE+'lang').text='ru'
                E.SubElement(item,common.localized.CORE+'content').text='Новое имя'
                raw=b'\xef\xbb\xbf'+row['owner'].encode('utf-8')
                path=profiles.owner_profiles()[row['kind']]['owner_common_path']
                actual,name=common.patch(raw,path,before,after,row['owner_id'],allow_rename=True)
                parsed=s.Parser(actual.decode('utf-8-sig')).documents()[0]
                values=profiles.owner_common(parsed,row['kind'])
                self.assertEqual(s.val(values[2]),name)
                self.assertEqual(s.val(values[4]),props.findtext(common.Q+'Comment'))
                self.assertEqual(s.render(values[3]),'{1,"ru","Новое имя"}')
                restored,_=common.patch(actual,path,after,before,row['owner_id'],allow_rename=True)
                self.assertEqual(restored,raw)
                original=s.Parser(row['owner']).documents()[0]
                source_values=profiles.owner_common(original,row['kind'])
                values[2:5]=copy.deepcopy(source_values[2:5])
                self.assertEqual(s.render(parsed),s.render(original))

    def test_source_mismatch_and_unapproved_rename_reject(self):
        for row in self.rows:
            root=E.fromstring(row['xml']);path=profiles.owner_profiles()[row['kind']]['owner_common_path'];raw=row['owner'].encode('utf-8')
            after=copy.deepcopy(root);after[0].find(common.Q+'Properties/'+common.Q+'Name').text='ChangedName'
            with self.subTest(kind=row['kind']),self.assertRaisesRegex(ValueError,'complete-export plan'):
                common.patch(raw,path,root,after,row['owner_id'])
            stale=copy.deepcopy(root);stale[0].find(common.Q+'Properties/'+common.Q+'Comment').text='Stale baseline'
            with self.assertRaisesRegex(ValueError,'Source common properties differ'):
                common.patch(raw,path,stale,after,row['owner_id'],allow_rename=True)

    def test_common_properties_match_independent_designer_import_for_all_21_classes(self):
        witness=json.loads(Path(__file__).with_name('fixtures').joinpath('owner_common_properties_851.json').read_text(encoding='utf-8'))
        self.assertEqual({row['kind'] for row in witness['samples']},set(profiles.owner_profiles()))
        for row in witness['samples']:
            with self.subTest(kind=row['kind']):
                source=row['source'].encode('utf-8')
                raw,_=common.patch(source,profiles.owner_profiles()[row['kind']]['owner_common_path'],E.fromstring(row['before_xml']),E.fromstring(row['xml']),row['id'])
                actual=profiles.owner_common(s.Parser(raw.decode('utf-8-sig')).documents()[0],row['kind'])
                self.assertEqual(s.render(actual[2:5]),row['native_common'])

    def test_derived_generated_names_follow_owner_rename_but_identifiers_remain_protected(self):
        generated='{'+common.xml_namespaces.READABLE+'}GeneratedType'
        checked=0
        for row in self.rows:
            before=E.fromstring(row['xml']);after=copy.deepcopy(before)
            old=before[0].findtext(common.Q+'Properties/'+common.Q+'Name');name='Renamed'+row['kind']
            after[0].find(common.Q+'Properties/'+common.Q+'Name').text=name
            nodes=after[0].findall(common.Q+'InternalInfo/'+generated)
            for node in nodes:
                value=node.get('name','')
                if value.endswith('.'+old):node.set('name',value[:-len(old)]+name)
            import metadata_structure
            xml_kind=metadata_structure.profile(row['kind'])['xml_name'];prefix=xml_kind+'.'+old+'.'
            for node in after[0].iter('{'+common.xml_namespaces.READABLE+'}Field'):
                if (node.text or '').startswith(prefix):node.text=xml_kind+'.'+name+'.'+node.text[len(prefix):]
            with self.subTest(kind=row['kind']):
                retained=lambda root:metadata_owner_change.retained_xml(root,row['kind'],ignore_common_properties=True)
                self.assertEqual(retained(before),retained(after))
                if not nodes:continue
                checked+=1
                saved=nodes[0].get('name');nodes[0].set('name','UnrelatedType.'+name)
                self.assertNotEqual(retained(before),retained(after))
                nodes[0].set('name',saved)
                nodes[0][0].text='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
                self.assertNotEqual(retained(before),retained(after))
        self.assertGreater(checked,10)

    def test_four_opaque_owner_renames_match_complete_independent_native_bodies(self):
        witness=json.loads(Path(__file__).with_name('fixtures').joinpath('opaque_owner_rename_851.json').read_text(encoding='utf-8'))
        from test_defined_type_forms import signature
        self.assertEqual({row['kind'] for row in witness['samples']},{'BusinessProcess','CalculationRegister','ExchangePlan','FilterCriterion'})
        for row in witness['samples']:
            with self.subTest(kind=row['kind']):
                before,after=E.fromstring(row['before_xml']),E.fromstring(row['xml'])
                retained=lambda root:metadata_owner_change.retained_xml(root,row['kind'],ignore_common_properties=True,ignore_form_properties=True)
                self.assertEqual(retained(before),retained(after))
                raw,name=common.patch(row['source'].encode('utf-8'),profiles.owner_profiles()[row['kind']]['owner_common_path'],before,after,row['id'],allow_rename=True)
                self.assertEqual(name,row['name'])
                self.assertEqual(signature(s.Parser(raw.decode('utf-8-sig')).documents()),signature(s.Parser(row['body']).documents()))
                fields=after[0].findall('.//{'+common.xml_namespaces.READABLE+'}Field')
                if fields:
                    fields[0].text=(fields[0].text or '')+'.UnsupportedField'
                    self.assertNotEqual(retained(before),retained(after))


if __name__=='__main__':unittest.main()
