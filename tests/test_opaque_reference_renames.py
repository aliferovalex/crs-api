"""Independent native witnesses keep incoming UUID references on target rename."""
import json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import opaque_owner_references as aliases,metadata_targets as targets
import metadata_identifiers as ids,native_metadata as s,metadata_owner_change

ROOT='11111111-2222-4333-8444-555555555555'


class OpaqueReferenceRenameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=json.loads(Path(__file__).with_name('fixtures').joinpath('opaque_reference_renames_851.json').read_text(encoding='utf-8'))['samples']

    def fixture(self,row):
        before,after=E.fromstring(row['before_xml']),E.fromstring(row['xml'])
        name=lambda root:root[0].findtext(aliases.Q+'Properties/'+aliases.Q+row['property']).split('.',1)[1]
        root=targets.Target(ROOT,ids.class_id('Configuration'),s.ZERO,s.ZERO,'Configuration',frozenset())
        old=targets.Target(row['target_id'],ids.class_id(row['target_kind']),ROOT,s.ZERO,name(before),frozenset())
        new=targets.Target(old.object_id,old.class_id,old.parent_id,old.owner_id,name(after),old.children)
        return before,after,targets.Index([root,old]),targets.Index([root,new],{old.object_id:(old.name,new.name)})

    def test_each_changed_xml_reference_resolves_to_the_unchanged_native_uuid(self):
        for row in self.rows:
            with self.subTest(kind=row['kind']):
                before,after,source,final=self.fixture(row);saved=E.tostring(before),E.tostring(after)
                body=s.Parser(row['source']).documents()[0];original=s.render(body)
                a,b=aliases.equivalent_roots(before,after,row['kind'],source,final,body=body)
                self.assertEqual(metadata_owner_change.canonical(a),metadata_owner_change.canonical(b))
                self.assertEqual(a[0].findtext(aliases.Q+'Properties/'+aliases.Q+row['property']),row['target_id'])
                self.assertEqual((E.tostring(before),E.tostring(after)),saved);self.assertEqual(s.render(body),original)

    def test_forged_rename_missing_ambiguous_or_different_target_reject(self):
        for row in self.rows:
            before,after,source,final=self.fixture(row);root,target=final.targets
            with self.subTest(kind=row['kind']):
                with self.assertRaisesRegex(ValueError,'not authorized'):
                    aliases.equivalent_roots(before,after,row['kind'],source,targets.Index(final.targets))
                for values in ([root],[root,target,target]):
                    with self.assertRaisesRegex(ValueError,'Missing or ambiguous'):
                        aliases.equivalent_roots(before,after,row['kind'],source,targets.Index(values,final.renames))
                foreign=targets.Target('aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',target.class_id,ROOT,s.ZERO,target.name,frozenset())
                with self.assertRaisesRegex(ValueError,'Changing opaque reference UUID'):
                    aliases.equivalent_roots(before,after,row['kind'],source,targets.Index([root,foreign],final.renames))

    def test_native_snapshot_uuid_and_unmapped_properties_remain_protected(self):
        for row in self.rows:
            before,after,source,final=self.fixture(row);body=s.Parser(row['source']).documents()[0]
            path=row['path'];node=body
            for index in path[:-1]:node=node[index]
            node[path[-1]]=s.atom(s.ZERO)
            with self.subTest(kind=row['kind']),self.assertRaisesRegex(ValueError,'native snapshot'):
                aliases.equivalent_roots(before,after,row['kind'],source,final,body=body)
            for root,value in ((before,'literal before'),(after,'literal after')):
                E.SubElement(root[0].find(aliases.Q+'Properties'),aliases.Q+'Unsupported').text=value
            a,b=aliases.equivalent_roots(before,after,row['kind'],source,final)
            self.assertNotEqual(metadata_owner_change.retained_xml(a,row['kind'],ignore_common_properties=True,ignore_form_properties=True),metadata_owner_change.retained_xml(b,row['kind'],ignore_common_properties=True,ignore_form_properties=True))


if __name__=='__main__':unittest.main()
