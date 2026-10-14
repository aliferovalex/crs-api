"""XML adapter/upstream model contract and upstream loss detection."""
import copy,unittest
from unittest.mock import patch
import metadata_serializer as s
import v8unpack_backend as backend
import managed_form_xml as forms
import test_managed_form_xml as fixture
import managed_form_serializer
import test_catalog_form_serializer as creation


class BackendTests(unittest.TestCase):
    def test_raw_model_preserves_quotes_base64_and_nested_arrays(self):
        docs=s.Parser('{1,"a""b",{#base64:YQ==}}').documents()
        model=backend.to_model(docs)
        self.assertEqual(model,[['1','"a""b"',['#base64:YQ==']]])
        self.assertEqual(backend.signature(s.Parser(backend.assemble(model).decode('utf-8-sig')).documents()),backend.signature(docs))

    def test_whole_xml_exposes_tree_and_data_and_upstream_assembles_it(self):
        r=creation.fixture();r.update(form_xml=fixture.xml(),module_text='// entire module')
        raw=fixture.extra(managed_form_serializer.serialize(r))
        paths={'Object.Code':s.Parser('{2,{1},{-2}}').documents()[0],
               'Object.Description':s.Parser('{2,{1},{-3}}').documents()[0]}
        model=forms.model_from_xml(raw,fixture.xml(fields=[('Renamed',2,'Description')]),'// replaced',paths,'XML_Catalog')
        self.assertEqual([n['name'] for n in model['elements']['tree']],['Renamed'])
        self.assertIn('Renamed',model['elements']['data'])
        result=backend.assemble_form(model)
        interface=forms.interface(result)
        self.assertEqual(s.val(interface[2]),'// replaced')
        index,count,end=forms.elements.form_collection(interface)
        self.assertEqual(count,1);self.assertEqual(s.val(interface[1][index+2][6]),'Renamed')

    def test_upstream_loss_is_rejected(self):
        r=creation.fixture();r.update(form_xml=fixture.xml())
        raw=fixture.extra(managed_form_serializer.serialize(r));model=backend.form_model(forms.interface(raw))
        model['elements']['tree']=[]
        with self.assertRaisesRegex(ValueError,'changed XML-mapped'):
            backend.assemble_form(model)

    def test_incompatible_runtime_is_rejected(self):
        backend.runtime()
        with patch('v8unpack.version.__version__','0.0'):
            with self.assertRaisesRegex(ValueError,'Expected v8unpack'):backend.runtime()

    def test_long_quoted_text_is_not_rewrapped_as_base64(self):
        module='// Native table creation through v8unpack\r\nProcedure CRSTableProbe() Export\r\nEndProcedure\r\n'
        docs=[[s.atom(module,True),s.atom('A'*128,True),s.atom('"__crs_v8_token_0__"',True)]]
        assembled=backend.assemble(backend.to_model(docs))
        self.assertEqual(backend.signature(s.Parser(assembled.decode('utf-8-sig')).documents()),backend.signature(docs))


if __name__=='__main__':unittest.main()
