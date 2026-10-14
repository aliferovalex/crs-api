"""Whole-file XML replacement and identical creation/change interfaces."""
import base64
import unittest
from xml.etree import ElementTree as E
import managed_form_xml as x
import managed_form_serializer
import managed_form_change
import external_data
import metadata_serializer as s
import test_managed_form_change as change
import test_catalog_form_serializer as creation


def xml(owner='XML_Catalog', fields=(('Description',2,'Description'),('Code',1,'Code'))):
    root=E.Element(x.Q+'Form',version='2.21')
    E.SubElement(root,x.Q+'UseForFoldersAndItems').text='Items'
    E.SubElement(root,x.Q+'AutoCommandBar',name='FormCommandBar',id='-1')
    items=E.SubElement(root,x.Q+'ChildItems')
    for name,number,path in fields:
        node=E.SubElement(items,x.Q+'InputField',name=name,id=str(number))
        E.SubElement(node,x.Q+'DataPath').text='Object.'+path
    attr=E.SubElement(E.SubElement(root,x.Q+'Attributes'),x.Q+'Attribute',name='Object',id='1')
    E.SubElement(E.SubElement(attr,x.Q+'Type'),'{'+x.CORE+'}Type').text='cfg:CatalogObject.'+owner
    E.SubElement(attr,x.Q+'MainAttribute').text='true'
    return E.tostring(root,encoding='unicode')


def extra(result):
    raw=s.inflate(base64.b64decode(result['data'])[18:]);_,pos=s.read_record(raw,0)
    storage,_=s.read_record(raw,pos+4);_,pos=s.read_record(storage,12)
    _,pos=s.read_record(storage,pos);external,_=s.read_record(storage,pos)
    return s.inflate(external)


class XMLTests(unittest.TestCase):
    def test_complete_list_reorders_removes_renames_and_replaces_module(self):
        r=change.fixture();r.pop('attribute_name')
        parent=external_data.extract(base64.b64decode(r['storage']),s.val(s.context_metadata(base64.b64decode(r['context']),r['object_id'])[0][3]))
        owner=s.Parser(s.inflate(base64.b64decode(parent['data'])).decode('utf-8-sig')).documents()[0]
        name=s.val(owner[1][9][1][2])
        r.update(form_xml=xml(name,[('Renamed',2,'Description'),('AttributeField',20,'TestAttribute')]),
                 module_text='&AtClient\nProcedure Test()\n    Message("A & B");\nEndProcedure')
        f=x.interface(extra(managed_form_change.serialize(r)));i,n,end=x.elements.form_collection(f)
        self.assertEqual(n,2)
        self.assertEqual([s.val(f[1][j+1][6]) for j in range(i+1,end,2)],['Renamed','AttributeField'])
        self.assertIn('Message("A & B")',s.val(f[2]));self.assertIn('\r\n',s.val(f[2]))
        self.assertIn('0,',s.render(f[1][end-1][11]))

    def test_creation_and_change_use_same_conversion(self):
        r=creation.fixture();r.update(form_xml=xml(),module_text='// identical module')
        result=managed_form_serializer.serialize(r);native=extra(result)
        self.assertEqual(native,x.convert(native,xml(),r['module_text'],
            {'Object.Code':s.Parser('{2,{1},{-2}}').documents()[0],
             'Object.Description':s.Parser('{2,{1},{-3}}').documents()[0]},'XML_Catalog'))

    def test_rejects_unknown_properties_elements_paths_and_duplicate_ids(self):
        r=creation.fixture()
        bad=[xml().replace('InputField','Button'),xml().replace('Object.Code','Object.Missing'),
             xml().replace('id="2"','id="1"'),xml().replace('</ns0:Form>','<ns0:Title>Lost</ns0:Title></ns0:Form>'),
             xml('WrongCatalog')]
        for value in bad:
            with self.subTest(value=value),self.assertRaises(ValueError):
                managed_form_serializer.serialize(dict(r,form_xml=value))

    def test_native_auxiliary_names_and_omitted_or_empty_module(self):
        r=creation.fixture();r.update(form_xml=xml(),module_text='// preserved')
        native=extra(managed_form_serializer.serialize(r))
        root=E.fromstring(xml())
        field=root.find(x.Q+'ChildItems')[0]
        E.SubElement(field,x.Q+'ContextMenu',name='MenuCustom',id='30')
        E.SubElement(field,x.Q+'ExtendedTooltip',name='TooltipCustom',id='31')
        paths={name:s.Parser(value).documents()[0] for name,value in
               [('Object.Code','{2,{1},{-2}}'),('Object.Description','{2,{1},{-3}}')]}
        result=x.convert(native,E.tostring(root,encoding='unicode'),paths=paths,object_name='XML_Catalog')
        form=x.interface(result)
        self.assertEqual(s.val(form[2]),'// preserved')
        self.assertIn('"MenuCustom"',result.decode('utf-8-sig'))
        self.assertIn('"TooltipCustom"',result.decode('utf-8-sig'))
        self.assertEqual(s.val(x.interface(x.convert(result,module_text=''))[2]),'')


if __name__=='__main__':unittest.main()
