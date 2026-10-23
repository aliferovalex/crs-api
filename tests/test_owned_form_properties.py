"""Every native form-selection slot is patched without rebuilding its owner."""
import copy,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import owned_form_properties as roles,metadata_targets as targets
import metadata_object_xml
import managed_form_profiles as owners, native_metadata as s
import metadata_owner_change
import object_xml_profiles, metadata_object_xml, native_collection_editor
import xml_namespaces


import metadata_identifiers
class OwnedFormPropertiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.witness=json.loads(Path(__file__).with_name('fixtures').joinpath('owned_form_properties_851.json').read_text(encoding='utf-8'))
        cls.index=targets.Index(targets.Target(**dict(row,children=frozenset(tuple(pair) for pair in row['children']))) for row in cls.witness['targets'])

    def test_all_21_owner_classes_and_95_native_role_slots_are_mapped(self):
        self.assertEqual(roles.profiles(),self.witness['mapping'])
        self.assertEqual(set(roles.profiles()),set(owners.owner_profiles()))
        self.assertEqual(sum(len(row['properties']) for row in roles.profiles().values()),95)
        for row in self.witness['owners']:
            root=E.fromstring(row['xml']);raw=row['owner'].encode('utf-8')
            actual,old,new=roles.patch(raw,row['kind'],row['owner_id'],root,root,self.index,self.index)
            self.assertEqual(actual,raw);self.assertEqual(old,new)

    def test_each_role_can_be_cleared_changing_only_its_native_atom(self):
        for row in self.witness['owners']:
            before=E.fromstring(row['xml']);raw=row['owner'].encode('utf-8')
            for name,path in roles.profiles()[row['kind']]['properties'].items():
                after=copy.deepcopy(before);after[0].find(roles.Q+'Properties/'+roles.Q+name).text=None
                with self.subTest(kind=row['kind'],property=name):
                    actual,old,new=roles.patch(raw,row['kind'],row['owner_id'],before,after,self.index,self.index)
                    source=s.Parser(row['owner']).documents()[0];node=roles.at(source,path)
                    expected=row['owner'][:node.start]+s.ZERO+row['owner'][node.end:]
                    self.assertEqual(actual.decode('utf-8'),expected);self.assertEqual(new[name],s.ZERO)
                    restored,_,_=roles.patch(actual,row['kind'],row['owner_id'],after,before,self.index,self.index)
                    self.assertEqual(restored,raw)
                    self.assertEqual(metadata_owner_change.retained_xml(before,row['kind'],ignore_form_properties=True),metadata_owner_change.retained_xml(after,row['kind'],ignore_form_properties=True))

    def test_foreign_missing_forms_source_mismatch_and_unknown_layout_reject(self):
        for row in self.witness['owners']:
            before=E.fromstring(row['xml']);raw=row['owner'].encode('utf-8');role=row['roles'][0]
            after=copy.deepcopy(before);after[0].find(roles.Q+'Properties/'+roles.Q+role['property']).text=role['reference']+'Missing'
            with self.subTest(kind=row['kind']),self.assertRaisesRegex(ValueError,'owned form reference'):
                roles.patch(raw,row['kind'],row['owner_id'],before,after,self.index,self.index)
            bad=copy.deepcopy(before);bad[0].find(roles.Q+'Properties/'+roles.Q+role['property']).text=None
            with self.assertRaisesRegex(ValueError,'Source form role differs'):
                roles.patch(raw,row['kind'],row['owner_id'],bad,before,self.index,self.index)
            body=s.Parser(row['owner']).documents()[0];body[0]=s.atom(999)
            with self.assertRaisesRegex(ValueError,'form role layout'):
                roles.patch(s.native_body_bytes([body]),row['kind'],row['owner_id'],before,bad,self.index,self.index)
            untouched=s.native_body_bytes([body])
            self.assertEqual(roles.patch(untouched,row['kind'],row['owner_id'],before,before,self.index,self.index)[0],untouched)

    def test_full_profiles_combine_comment_and_every_form_role_from_the_same_map(self):
        checked=set()
        expected={(row['kind'],role['property']) for row in self.witness['owners'] if row['kind'] in object_xml_profiles.profiles() for role in row['roles']}
        for row in self.witness['owners']:
            kind=row['kind']
            if kind not in object_xml_profiles.profiles():continue
            root=E.fromstring(row['xml']);props=root[0].find(roles.Q+'Properties')
            props.find(roles.Q+'Comment').text='Combined role and comment'
            for name in roles.profiles()[kind]['properties']:props.find(roles.Q+name).text=None
            text=xml_namespaces.render(root,row['xml']);source=s.Parser(row['owner']).documents()[0]
            with self.subTest(kind=kind):
                if kind=='Catalog':
                    cls=metadata_identifiers.class_id('CatalogForm')
                    forms={target.name:target.object_id for target in self.index.targets if target.parent_id==row['owner_id'] and target.class_id==cls}
                    # Separately stored templates are restored by the packet builder.
                    children=root[0].find(roles.Q+'ChildObjects')
                    for node in list(children):
                        if node.tag==roles.Q+'Template':children.remove(node)
                    source[3]=[source[3][0],s.atom(0)]
                    raw,_=metadata_object_xml.change(xml_namespaces.render(root,row['xml']), '8.5.1.1529', 'Catalog', source, forms, reference_objects=self.index)
                else:
                    _,_,raw,_=metadata_object_xml.object_xml(native_collection_editor.strip_xml(text,kind),'8.5.1.1529',kind,self.index)
                actual=s.Parser(raw.decode('utf-8-sig')).documents()[0]
                for name,path in roles.profiles()[kind]['properties'].items():self.assertEqual(s.val(roles.at(actual,path)),s.ZERO)
                self.assertEqual(s.val(owners.owner_common(actual,kind)[4]),'Combined role and comment')
                checked.update((kind,name) for name in roles.profiles()[kind]['properties'])
        self.assertEqual(checked,expected)
        self.assertIn(('SettingsStorage','DefaultSaveForm'),checked)


if __name__=='__main__':unittest.main()
