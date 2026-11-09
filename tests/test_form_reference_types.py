"""Form and metadata declarations share generated categories and type groups."""
import sys,types,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import form_attribute_types as forms
import metadata_type_references as metadata
import metadata_type_sets as groups
import native_references


def form(value,tag='Type'):
    return '<Form xmlns="'+forms.Q[1:-1]+'" xmlns:v8="'+forms.CORE[1:-1]+'"><Attributes><Attribute name="Local" id="1"><Type><v8:'+tag+'>'+value+'</v8:'+tag+'></Type></Attribute></Attributes></Form>'


class FormReferenceTypesTests(unittest.TestCase):
    def test_form_categories_use_the_same_rules_as_metadata(self):
        for value in ('cfg:CatalogObject.Test','cfg:DocumentObject.Test','cfg:ChartOfAccountsRef.Test','cfg:ChartOfCharacteristicTypesRef.Test','cfg:Characteristic.Test'):
            with self.subTest(value=value):
                self.assertEqual(forms.required(form(value)),{value})
                self.assertEqual(forms.reference_name(value),metadata.reference_name(value))
        with self.assertRaisesRegex(ValueError,'Unsupported metadata reference'):
            forms.required(form('cfg:Unknown.Test'))

    def test_resolver_preserves_object_and_reference_categories(self):
        reader=types.SimpleNamespace(type_id=mock.Mock(return_value='native-generated-type'))
        with mock.patch.object(native_references,'catalog',return_value=reader):
            value='cfg:CatalogObject.Test'
            self.assertEqual(forms.resolve(form(value),{},b'source'),{value:'native-generated-type'})
            reader.type_id.assert_called_once_with('Catalog','Test','Object',storage=b'source')

    def test_type_sets_use_shared_platform_id_and_root_feature_dependency(self):
        value='cfg:CatalogObject';reader=types.SimpleNamespace(request={})
        with mock.patch.object(native_references,'catalog',return_value=reader),mock.patch.object(groups,'dependencies',return_value={'root-feature'}) as dependencies:
            xml=form(value,'TypeSet')
            self.assertEqual(forms.resolve(xml,{}),{value:groups.profile()[value]})
            self.assertEqual(forms.dependencies(xml,reader,b'source'),{'root-feature'})
            dependencies.assert_called_once_with({value},reader,b'source')

    def test_main_object_type_is_not_counted_as_a_local_dependency(self):
        xml=form('cfg:CatalogObject.Test').replace('</Attribute>','<MainAttribute>true</MainAttribute></Attribute>')
        self.assertEqual(forms.required(xml),set())


if __name__=='__main__':unittest.main()
