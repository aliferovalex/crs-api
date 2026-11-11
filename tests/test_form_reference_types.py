"""Form and metadata declarations share generated categories and type groups."""
import sys,types,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import form_attribute_types as forms
import metadata_type_references as metadata
import metadata_type_sets as groups
import native_references
import metadata_references
import native_metadata as s


def form(value,tag='Type'):
    return '<Form xmlns="'+forms.Q[1:-1]+'" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:v8="'+forms.CORE[1:-1]+'"><Attributes><Attribute name="Local" id="1"><Type><v8:'+tag+'>'+value+'</v8:'+tag+'></Type></Attribute></Attributes></Form>'


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

    def test_reference_namespace_is_independent_of_prefix_spelling(self):
        xml=form('cfg:CatalogRef.Test').replace('xmlns:cfg=', 'xmlns:project=').replace(
            '>cfg:CatalogRef.Test<','>project:CatalogRef.Test<')
        self.assertEqual(forms.required(xml),{'cfg:CatalogRef.Test'})
        self.assertEqual(metadata.required(xml),{'cfg:CatalogRef.Test'})

    def test_local_prefix_binding_wins_over_root_binding(self):
        xml=form('cfg:CatalogRef.Test').replace('</Attribute>',
            '<Columns><Column name="Foreign" id="1" xmlns:cfg="urn:foreign">'
            '<Type><v8:Type>cfg:CatalogRef.Other</v8:Type></Type></Column>'
            '<Column name="Project" id="2" xmlns:project="'+metadata.CONFIG_NAMESPACE+'">'
            '<Type><v8:Type>project:DocumentRef.Other</v8:Type></Type></Column>'
            '</Columns></Attribute>')
        expected={'cfg:CatalogRef.Test','cfg:DocumentRef.Other'}
        self.assertEqual(forms.required(xml),expected)
        self.assertEqual(metadata.required(xml),expected)

    def test_unbound_prefix_is_rejected_instead_of_silently_losing_a_dependency(self):
        xml=form('missing:CatalogRef.Test')
        for reader in (forms.required,metadata.required):
            with self.subTest(reader=reader.__module__),self.assertRaisesRegex(ValueError,'Unbound XML type QName'):
                reader(xml)

    def test_parameters_and_nested_declarations_share_metadata_type_resolution(self):
        xml=('<Form xmlns="'+forms.Q[1:-1]+'" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:v8="'+forms.CORE[1:-1]+'">'
             '<Parameters><Parameter name="Selected" id="1"><Type>'
             '<v8:Type>cfg:CatalogRef.Test</v8:Type><v8:TypeSet>cfg:DocumentRef</v8:TypeSet>'
             '</Type></Parameter></Parameters><Attributes><Attribute name="Rows" id="1">'
             '<Columns><Column name="Value" id="1"><Type><v8:Type>cfg:EnumRef.Test</v8:Type>'
             '</Type></Column></Columns></Attribute></Attributes></Form>')
        index=types.SimpleNamespace(reference=mock.Mock())
        expected={'cfg:CatalogRef.Test','cfg:DocumentRef','cfg:EnumRef.Test'}
        self.assertEqual(forms.required(xml,index),expected)
        self.assertEqual(metadata.required(xml,index),expected)
        reader=types.SimpleNamespace(request={'_compiled_types':types.SimpleNamespace(
            reference=mock.Mock(),object_ids_required=lambda refs: {'owner:'+ref for ref in refs})})
        self.assertEqual(forms.dependencies(xml,reader),{'owner:'+ref for ref in expected})

    def test_main_attribute_columns_still_require_their_own_reference_types(self):
        xml=form('cfg:CatalogObject.Test').replace('</Attribute>',
            '<MainAttribute>true</MainAttribute><Columns><Column name="Other" id="1">'
            '<Type><v8:Type>cfg:DocumentRef.Other</v8:Type></Type></Column></Columns></Attribute>')
        self.assertEqual(forms.required(xml),{'cfg:DocumentRef.Other'})

    def test_unknown_or_malformed_parameter_types_cannot_bypass_validation(self):
        for declaration in ('<v8:Type>cfg:Unknown.Test</v8:Type>',
                            '<v8:Type extra="1">cfg:CatalogRef.Test</v8:Type>'):
            xml=form('cfg:CatalogRef.Test').replace('<Attributes><Attribute','<Parameters><Parameter').replace(
                '</Attribute></Attributes>','</Parameter></Parameters>').replace(
                '<v8:Type>cfg:CatalogRef.Test</v8:Type>',declaration)
            with self.subTest(declaration=declaration),self.assertRaises(ValueError):forms.required(xml)

    def test_removing_last_parameter_reference_removes_only_its_proven_dependency(self):
        parent='11111111-1111-4111-8111-111111111111'
        target='22222222-2222-4222-8222-222222222222'
        generated='33333333-3333-4333-8333-333333333333'
        opaque='44444444-4444-4444-8444-444444444444'
        xml=form('cfg:CatalogRef.Test').replace('<Attributes><Attribute','<Parameters><Parameter').replace(
            '</Attribute></Attributes>','</Parameter></Parameters>')
        final=types.SimpleNamespace(reference=mock.Mock(),object_ids_required=lambda refs: {target} if refs else set())
        source=types.SimpleNamespace(owner_for_generated=lambda value: target if value==generated else None,
                                     object_ids_required=lambda refs:set())
        request={'_compiled_types':final,'_source_types':source}
        reader=types.SimpleNamespace(request=request)
        with mock.patch.object(native_references,'catalog',return_value=reader),mock.patch(
                'native_form_reader.interface',return_value=[[s.atom(generated)]]):
            added=metadata_references.form_relations(xml,request,parent,{opaque:1})
            self.assertEqual(s.metadata_relations(added),{opaque:1,parent:1,target:1})
            removed=metadata_references.form_relations('<Form/>',request,parent,
                s.metadata_relations(added),raw=b'source form')
            self.assertEqual(s.metadata_relations(removed),{opaque:1,parent:1})


if __name__=='__main__':unittest.main()
