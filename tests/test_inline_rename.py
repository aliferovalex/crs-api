"""Inline names resolve through the final owner while form UUID bindings survive."""
import base64,json,sys,unittest,zlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_graph
import compiled_metadata as compiled
import native_metadata as s


class InlineRenameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('native_inline_rename.json').read_text(encoding='utf-8'))
        cls.case=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))

    def body(self,phase):return s.Parser(self.case[phase]).documents()

    def test_same_native_form_validates_against_each_matching_owner_and_xml(self):
        for phase in ('before','after'):
            with self.subTest(phase=phase):
                compiled.validate_form_interface(self.case[phase+'_xml'],self.body(phase)[0],
                    'Catalog',self.case['interface'].encode(),{})

    def test_names_from_other_owner_version_are_rejected(self):
        for owner,xml in [('before','after'),('after','before')]:
            with self.subTest(owner=owner),self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
                compiled.validate_form_paths(self.case[xml+'_xml'],self.body(owner)[0],'Catalog')

    def test_uuid_inventory_is_preserved_while_common_feature_name_changes(self):
        before=self.body('before');after=self.body('after');oid=self.case['feature_id']
        self.assertEqual(compiled.guid_counts(before),compiled.guid_counts(after))
        compiled_graph.common_identity(before,oid,'CRSAPI_TestAttribute')
        compiled_graph.common_identity(after,oid,'CRSAPI_RenamedAttribute')
        with self.assertRaisesRegex(ValueError,'common metadata name differs'):
            compiled_graph.common_identity(after,oid,'CRSAPI_TestAttribute')


if __name__=='__main__':unittest.main()
