"""Bindings from independently exported tabular forms survive nested renames."""
import base64,json,sys,unittest,zlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_metadata as compiled
import native_form_reader as forms
import native_metadata as s
import native_tabular as tabular


class TabularFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('native_tabular_form.json').read_text(encoding='utf-8'))
        cls.case=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))

    def body(self,phase):return s.Parser(self.case[phase]['body']).documents()[0]

    def test_complete_interfaces_match_their_final_owner_in_every_phase(self):
        for phase in ('init','create-tabular-form','rename-nested','remove-tabular-form'):
            with self.subTest(phase=phase):
                row=self.case[phase]
                compiled.validate_form_interface(row['xml'],self.body(phase),'Catalog',row['interface'].encode(),{})

    def test_nested_rename_keeps_uuid_bindings_and_native_interface(self):
        before=self.body('create-tabular-form');after=self.body('rename-nested')
        first=tabular.collection(before)[0];last=tabular.collection(after)[0]
        self.assertEqual(tabular.feature_ids(first),tabular.feature_ids(last))
        self.assertEqual(len(tabular.feature_ids(first)),5)
        self.assertEqual(compiled.guid_counts(before),compiled.guid_counts(after))
        paths=forms.object_paths(before,'Catalog');renamed=forms.object_paths(after,'Catalog')
        self.assertIn('Object.CRSAPI_Rows',paths.tables)
        self.assertEqual(paths.types['Object.CRSAPI_Rows.Text'],'S')
        self.assertEqual(paths.types['Object.CRSAPI_Rows.Quantity'],'N')
        self.assertEqual(paths.types['Object.CRSAPI_Rows.Active'],'B')
        self.assertEqual(paths.types['Object.CRSAPI_Rows.Moment'],'D')
        self.assertNotIn('Object.CRSAPI_Rows.Text',renamed)
        self.assertEqual(s.render(paths['Object.CRSAPI_Rows.Text']),s.render(renamed['Object.CRSAPI_Rows.RenamedText']))
        self.assertEqual(self.case['create-tabular-form']['interface'],self.case['rename-nested']['interface'])

    def test_paths_from_other_owner_version_are_rejected(self):
        for owner,xml in [('create-tabular-form','rename-nested'),('rename-nested','create-tabular-form'),
                          ('remove-tabular-form','create-tabular-form')]:
            with self.subTest(owner=owner,xml=xml),self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
                compiled.validate_form_paths(self.case[xml]['xml'],self.body(owner),'Catalog')

    def test_removal_drops_all_tabular_paths_and_restores_original_owner(self):
        for phase in ('init','remove-tabular-form'):
            with self.subTest(phase=phase):
                self.assertEqual(tabular.collection(self.body(phase)),[])
                paths=forms.object_paths(self.body(phase),'Catalog')
                self.assertFalse(paths.tables)
                self.assertFalse(any(p.startswith('Object.CRSAPI_Rows') for p in paths))
        self.assertEqual(self.case['init']['body'],self.case['remove-tabular-form']['body'])


if __name__=='__main__':unittest.main()
