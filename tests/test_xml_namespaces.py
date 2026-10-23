"""QName values require their default namespace as well as explicit prefixes."""
import unittest
import sys
from pathlib import Path
from xml.etree import ElementTree as E
from xml.dom import minidom
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import xml_namespaces
import schema_content


class NamespaceTests(unittest.TestCase):
    def test_metadata_export_retains_literal_cr_in_complete_properties(self):
        import metadata_object_xml as metadata
        from test_object_change_serializer import fixture
        for kind in ('CommonModule','Catalog'):
            with self.subTest(kind=kind):
                request,_,_=fixture(kind)
                top=E.fromstring(request['object_xml'])
                top[0].find(metadata.Q+'Properties/'+metadata.Q+'Comment').text='first\rsecond'
                _,_,raw,_=metadata.create(xml_namespaces.serialize(top),request['platform'],kind)
                body=metadata.s.Parser(raw.decode('utf-8-sig')).documents()[0]
                restored=metadata.export(body,{},request['platform'],kind)
                reparsed=E.fromstring(xml_namespaces.serialize(restored))
                self.assertEqual(reparsed[0].findtext(metadata.Q+'Properties/'+metadata.Q+'Comment'),'first\rsecond')

    def test_literal_carriage_returns_survive_both_render_paths(self):
        xml='<Root xmlns="urn:root" xmlns:t="urn:type"><Value kind="t:Text">first&#13;second\nthird</Value></Root>'
        root,scopes=xml_namespaces.parse(xml)
        expected=root[0].text
        for bindings in (None,scopes):
            with self.subTest(scoped=bindings is not None):
                rewritten=xml_namespaces.render(root,xml,bindings)
                self.assertIn('&#13;',rewritten)
                reparsed=E.fromstring(rewritten)
                self.assertEqual(reparsed[0].text,expected)
                self.assertEqual(reparsed[0].get('kind'),'t:Text')

    def test_rewriting_preserves_unprefixed_schema_qnames(self):
        xml='<DataCompositionSchema xmlns="'+schema_content.SCHEMA+'" xmlns:xsi="'+schema_content.XSI+'"><dataSet xsi:type="DataSetQuery"/></DataCompositionSchema>'
        rewritten=xml_namespaces.render(E.fromstring(xml),xml)
        doc=minidom.parseString(rewritten);node=doc.getElementsByTagNameNS(schema_content.SCHEMA,'dataSet')[0]
        self.assertEqual(schema_content._qname(node,node.getAttributeNS(schema_content.XSI,'type')),(schema_content.SCHEMA,'DataSetQuery'))
        self.assertEqual(E.tostring(E.fromstring(rewritten)),E.tostring(E.fromstring(xml)))

    def test_explicit_qname_prefix_is_preserved_without_duplication(self):
        xml='<Root xmlns="urn:root" xmlns:t="urn:type" value="t:Reference"/>'
        rewritten=xml_namespaces.render(E.fromstring(xml),xml);again=xml_namespaces.render(E.fromstring(rewritten),rewritten)
        self.assertEqual(again.count('xmlns:t='),1);self.assertEqual(again.count('xmlns='),1)


if __name__=='__main__':unittest.main()
