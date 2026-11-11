"""Native contract for an inline reference attribute and its whole managed form."""
import base64,json,sys,unittest,zlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_metadata as compiled
import metadata_type_references as references
import native_metadata as s
import native_features
import native_object_profiles


class CompiledReferenceAttributeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('compiled_reference_attribute.json').read_text(encoding='utf-8'))
        cls.case=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))

    def body(self,stage):
        return s.Parser(self.case['stages'][stage]['owner']).documents()[0]

    def test_added_reference_attribute_and_control_bind_to_the_final_owner(self):
        for stage in ('before','added','removed'):
            row=self.case['stages'][stage]
            with self.subTest(stage=stage):
                compiled.validate_form_interface(row['form_xml'],self.body(stage),'Catalog',row['interface'].encode(),{})

    def test_new_form_cannot_bind_against_the_old_or_removed_attribute(self):
        xml=self.case['stages']['added']['form_xml']
        for stage in ('before','removed'):
            with self.subTest(stage=stage),self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
                compiled.validate_form_paths(xml,self.body(stage),'Catalog')

    def test_reference_type_and_feature_are_present_only_while_declared(self):
        for stage,present in [('before',False),('added',True),('removed',False)]:
            row=self.case['stages'][stage];body=[self.body(stage)]
            with self.subTest(stage=stage):
                self.assertEqual(references.required(row['owner_xml']),
                    {'cfg:DocumentRef.CRSAPI_TestDocument'} if present else set())
                self.assertEqual(self.case['attribute_id'] in compiled.guid_counts(body),present)
                self.assertEqual(bool(references.type_ids(body)),present)

    def test_existing_attribute_type_changes_preserve_features_and_the_unchanged_form(self):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('compiled_attribute_types.json').read_text(encoding='utf-8'))
        case=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))
        layout=native_object_profiles.layout('Catalog','8.5.1.1529');expected=None
        for stage,row in case['stages'].items():
            with self.subTest(stage=stage):
                body=s.Parser(row['owner']).documents()[0]
                features=set(native_features.features(body,layout))
                if expected is None:expected=features
                self.assertEqual(features,expected)
                declared={'reference':{'cfg:DocumentRef.CRSAPI_TestDocument'},
                          'self-reference':{'cfg:CatalogRef.CRSAPI_TestCatalog'}}.get(stage,set())
                self.assertEqual(references.required(row['owner_xml']),declared)
                self.assertEqual(bool(references.type_ids(body)),bool(declared))
                compiled.validate_form_interface(case['form_xml'],body,'Catalog',case['interface'].encode(),{})


if __name__=='__main__':unittest.main()
