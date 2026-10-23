"""Shared whole-file conversion for Document and CommonForm interfaces."""
import json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
import managed_form_xml as x
import native_metadata as s
import type_description_xml as types
import test_managed_form_xml as catalog


def native(kind):
    filename='document_form_layout_851.json' if kind=='Document' else 'common_form_layout_851.json'
    layout=json.loads(Path(x.__file__).with_name(filename).read_text(encoding='utf-8'))
    return layout['external_template'].replace('${catalog_object_type}','11111111-1111-4111-8111-111111111111').encode('utf-8')


def document_paths():
    import test_document_serializer as document
    import metadata_object_xml as objects
    raw=objects.create(document.xml().replace('XML_Document','Doc'),'8.5.1.1529','Document')[2]
    return x.object_paths(s.Parser(raw.decode('utf-8-sig')).documents()[0],'Document')


def common_xml(attributes=(('Message',1,'{"Pattern",{"S",100,1}}'),)):
    root=E.Element(x.Q+'Form',version='2.21');E.SubElement(root,x.Q+'AutoCommandBar',name='FormCommandBar',id='-1')
    items=E.SubElement(root,x.Q+'ChildItems');attrs=E.SubElement(root,x.Q+'Attributes')
    for name,number,pattern in attributes:
        field=E.SubElement(items,x.Q+'InputField',name=name,id=str(number));E.SubElement(field,x.Q+'DataPath').text=name
        attr=E.SubElement(attrs,x.Q+'Attribute',name=name,id=str(number));attr.append(types.export(s.Parser(pattern).documents()[0],x.Q+'Type'))
    return E.tostring(root,encoding='unicode')


class FormKindsTests(unittest.TestCase):
    def test_document_bindings_and_kind_guard(self):
        root=E.fromstring(catalog.xml('Doc',fields=(('Date',2,'Date'),('Number',1,'Number'))));root.remove(root.find(x.Q+'UseForFoldersAndItems'))
        root.find('.//{'+x.CORE+'}Type').text='cfg:DocumentObject.Doc'
        E.SubElement(root,x.Q+'AutoTime').text='CurrentOrLast'
        text=E.tostring(root,encoding='unicode');raw=x.convert(native('Document'),text,paths=document_paths(),object_name='Doc',kind='Document')
        form=x.interface(raw);index,count,end=x.elements.form_collection(form)
        self.assertEqual([s.val(form[1][i+1][6]) for i in range(index+1,end,2)],['Date','Number'])
        self.assertEqual(s.render(form[1][index+2][11]),'{2,{1},{-3}}')
        with self.assertRaises(ValueError):x.convert(native('Document'),text,object_name='Doc')
        with self.assertRaisesRegex(ValueError,'document form property'):x.convert(native('Document'),text.replace('CurrentOrLast','Current'),kind='Document')

    def test_scalar_attributes_whole_collection_and_empty_form(self):
        specs=(('Message',1,'{"Pattern",{"S",100,1}}'),('Amount',7,'{"Pattern",{"N",15,2,0}}'),('Flag',8,'{"Pattern",{"B"}}'),('Moment',9,'{"Pattern",{"D"}}'))
        raw=x.convert(native('CommonForm'),common_xml(specs),module_text='// whole form',kind='CommonForm')
        form=x.interface(raw);self.assertEqual(s.val(form[3][1]),'4');self.assertEqual(s.val(form[2]),'// whole form')
        for index,(name,number,pattern) in enumerate(specs):
            attr=form[3][index+2];self.assertEqual(s.val(attr[3]),name);self.assertEqual(s.render(attr[5]),pattern)
        replaced=x.interface(x.convert(raw,common_xml((specs[2],)),kind='CommonForm'))
        self.assertEqual(s.val(replaced[3][1]),'1');self.assertEqual(s.val(replaced[3][2][3]),'Flag')
        empty=E.fromstring(common_xml(()));empty.remove(empty.find(x.Q+'ChildItems'));empty.remove(empty.find(x.Q+'Attributes'))
        cleared=x.interface(x.convert(raw,E.tostring(empty,encoding='unicode'),kind='CommonForm'))
        self.assertEqual(s.val(cleared[3][1]),'0');self.assertEqual(s.val(cleared[2]),'// whole form')

    def test_duplicate_identifiers_names_and_unbound_fields_rejected(self):
        text=common_xml((('Message',1,'{"Pattern",{"B"}}'),('Flag',2,'{"Pattern",{"B"}}')))
        for bad in (text.replace('name="Flag"','name="message"'),text.replace('id="2"','id="1"'),text.replace('>Message</','>Missing</')):
            with self.subTest(xml=bad),self.assertRaises(ValueError):x.convert(native('CommonForm'),bad,kind='CommonForm')


if __name__=='__main__':unittest.main()
