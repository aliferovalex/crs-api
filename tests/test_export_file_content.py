"""Shared equality cannot erase application values or namespace bindings."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import xml_compare as compare


class ExportFileContentTests(unittest.TestCase):
    def same(self,left,right):return compare.file_equal('Object.xml',left.encode(),right.encode())

    def test_indentation_bom_and_line_endings_are_formatting(self):
        self.assertTrue(compare.file_equal('Object.xml',b'<Object><Name>Test</Name></Object>',
            b'\xef\xbb\xbf<Object>\r\n  <Name>Test</Name>\r\n</Object>'))
        self.assertTrue(compare.file_equal('Module.bsl',b'// same\n',b'\xef\xbb\xbf// same\r\n'))
        self.assertFalse(compare.file_equal('Module.bsl',b'// same\n',b'// same \n'))

    def test_qname_aliases_match_but_rebound_type_namespaces_do_not(self):
        xml='<Type xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:cfg="urn:config"><v8:Type>cfg:Ref.Test</v8:Type></Type>'
        self.assertTrue(self.same(xml,xml.replace('xmlns:cfg=','xmlns:project=').replace('cfg:Ref','project:Ref')))
        self.assertFalse(self.same(xml,xml.replace('urn:config','urn:foreign')))
        value='<Value xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:r="urn:readable" xsi:type="r:DesignTimeRef">Catalog.Test.EmptyRef</Value>'
        self.assertFalse(self.same(value,value.replace('urn:readable','urn:foreign')))

    def test_leaf_values_mixed_text_and_child_order_are_significant(self):
        for left,right in [('<Name>Same</Name>','<Name>Same </Name>'),
                           ('<Text>Hello <B>World</B>!</Text>','<Text>Hello <B>World</B>?</Text>'),
                           ('<Text>Hello <B>World</B></Text>','<Text>Hello<B>World</B></Text>'),
                           ('<Rows><A/><B/></Rows>','<Rows><B/><A/></Rows>'),
                           ('<Rows xml:space="preserve"><A/> </Rows>','<Rows xml:space="preserve"><A/></Rows>')]:
            with self.subTest(left=left):self.assertFalse(self.same(left,right))

    def test_schema_specific_values_do_not_hide_changed_prefix_bindings(self):
        for xml in ('<Color xmlns:style="urn:style">style:NormalText</Color>',
                    '<Color xmlns:style="urn:style" ref="style:NormalText"/>'):
            with self.subTest(xml=xml):self.assertFalse(self.same(xml,xml.replace('urn:style','urn:foreign')))
        self.assertTrue(self.same('<Name xmlns:unused="urn:one">Same</Name>',
                                  '<Name xmlns:unused="urn:other">Same</Name>'))

    def test_binary_and_missing_files_keep_exact_semantics(self):
        self.assertFalse(compare.file_equal('Template.bin',b'a\n',b'a\r\n'))
        self.assertFalse(compare.file_equal('Module.bsl',None,b''))
        self.assertTrue(compare.file_equal('Template.bin',b'\x00\xff',b'\x00\xff'))


if __name__=='__main__':unittest.main()
