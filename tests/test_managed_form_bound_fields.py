import sys, unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/Сериализация'))
import native_metadata as s, managed_form_xml as x, managed_form_operations as creation, v8unpack_backend as b
from test_managed_form_table import owner,xml as table_xml


def xml():
    root=table_xml(columns=('Text',));items=root.find(x.Q+'ChildItems');table=items[0];columns=table.find(x.Q+'ChildItems')
    # The tabular fixture contains Text and Quantity; add bool metadata separately.
    label=columns[0];label.tag=x.Q+'LabelField'
    checkbox=E.SubElement(items,x.Q+'CheckBoxField',name='Flag',id='220');E.SubElement(checkbox,x.Q+'DataPath').text='Object.Flag'
    events=E.SubElement(checkbox,x.Q+'Events');E.SubElement(events,x.Q+'Event',name='OnChange').text='FlagOnChange'
    return root


def paths():
    result=x.object_paths(owner(),'Catalog');result['Object.Flag']=s.Parser('{2,{1},{0,11111111-1111-4111-8111-111111111111}}').documents()[0];result.types['Object.Flag']='B'
    return result


def native(root):
    _,_,raw=creation.create_native('Catalog','FieldsForm','8.5.1.1529',owner())
    return x.convert(raw,E.tostring(root,encoding='unicode'),paths=paths(),object_name='XML_Catalog')


class FieldTests(unittest.TestCase):
    def test_shared_upstream_field_tree_and_checkbox_event(self):
        raw=native(xml());model=b.form_model(x.interface(raw));data=model['elements']['data']
        self.assertEqual(data['Flag']['raw'][5],'3');self.assertEqual(data['RowsTable/RowsText']['raw'][5],'1')
        self.assertEqual(data['Flag']['raw'][40][2],'"FlagOnChange"')

    def test_flags_and_complete_field_removal(self):
        root=xml();checkbox=root.find(x.Q+'ChildItems')[1]
        for prop,value in [('ReadOnly','true'),('Enabled','false'),('Visible','false')]:E.SubElement(checkbox,x.Q+prop).text=value
        raw=native(root);values=b.form_model(x.interface(raw))['elements']['data']['Flag']['raw']
        self.assertEqual((values[13],values[14],values[43]),('0','1','0'))
        root.find(x.Q+'ChildItems').remove(checkbox)
        converted=x.convert(raw,E.tostring(root,encoding='unicode'),paths=paths(),object_name='XML_Catalog')
        self.assertNotIn('Flag',b.form_model(x.interface(converted))['elements']['data'])

    def test_checkbox_rejects_nonboolean_binding_and_type_change(self):
        root=xml();root.find(x.Q+'ChildItems')[1].find(x.Q+'DataPath').text='Object.Description'
        with self.assertRaisesRegex(ValueError,'boolean DataPath'):native(root)
        raw=native(xml());root=xml();root.find(x.Q+'ChildItems')[1].tag=x.Q+'InputField'
        with self.assertRaisesRegex(ValueError,'Control type'):x.convert(raw,E.tostring(root,encoding='unicode'),paths=paths(),object_name='XML_Catalog')

    def test_common_form_checkbox_uses_scalar_attribute_type(self):
        root=E.Element(x.Q+'Form',version='2.21');E.SubElement(root,x.Q+'AutoCommandBar',name='FormCommandBar',id='-1')
        fields=E.SubElement(root,x.Q+'ChildItems');field=E.SubElement(fields,x.Q+'CheckBoxField',name='Flag',id='10');E.SubElement(field,x.Q+'DataPath').text='Flag'
        attrs=E.SubElement(root,x.Q+'Attributes');attr=E.SubElement(attrs,x.Q+'Attribute',name='Flag',id='10');typ=E.SubElement(attr,x.Q+'Type');E.SubElement(typ,'{'+x.CORE+'}Type').text='xs:boolean'
        _,_,raw=creation.create_native('CommonForm','FieldsForm','8.5.1.1529',None,interface_xml=E.tostring(root,encoding='unicode'))
        self.assertEqual(b.form_model(x.interface(raw))['elements']['data']['Flag']['raw'][11],['1',['10']])


if __name__=='__main__':unittest.main()
