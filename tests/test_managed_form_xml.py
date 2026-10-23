"""Whole-file XML replacement and identical creation/change interfaces."""
import base64
import unittest
from xml.etree import ElementTree as E
import managed_form_xml as x
import managed_form_operations
import external_data
import type_description_xml as types
import metadata_context
import native_metadata as s
import test_managed_form_operations as change
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
    def mixed_xml(self,owner='XML_Catalog'):
        root=E.fromstring(xml(owner));attrs=root.find(x.Q+'Attributes');items=root.find(x.Q+'ChildItems')
        for name,number,pattern in [('Message',7,'{"Pattern",{"S",100,1}}'),('Amount',8,'{"Pattern",{"N",15,2,0}}'),('Flag',9,'{"Pattern",{"B"}}'),('Moment',10,'{"Pattern",{"D"}}')]:
            attr=E.SubElement(attrs,x.Q+'Attribute',name=name,id=str(number))
            attr.append(types.export(s.Parser(pattern).documents()[0],x.Q+'Type'))
            field=E.SubElement(items,x.Q+'InputField',name=name,id=str(number+100))
            E.SubElement(field,x.Q+'DataPath').text=name
        # XML order is independent of which attribute is the main object.
        attrs.insert(2,attrs[0]);del attrs[0]
        return root

    def test_main_and_scalar_attributes_create_reorder_remove_and_keep_bindings(self):
        r=creation.fixture();root=self.mixed_xml();text=E.tostring(root,encoding='unicode')
        original=x.interface(extra(managed_form_operations.create(r)))[3][2]
        raw=extra(managed_form_operations.create(dict(r,form_xml=text,module_text='// mixed')))
        form=x.interface(raw);attrs=form[3][2:7]
        self.assertEqual([s.val(a[3]) for a in attrs],['Message','Object','Amount','Flag','Moment'])
        self.assertEqual(s.render(attrs[1]),s.render(original))
        index,count,end=x.elements.form_collection(form)
        self.assertEqual(count,6)
        fields={s.val(form[1][j+1][6]):form[1][j+1] for j in range(index+1,end,2)}
        self.assertEqual(s.render(fields['Message'][11]),'{1,{7}}')
        self.assertEqual(s.render(fields['Code'][11]),'{2,{1},{-2}}')
        a=root.find(x.Q+'Attributes');a[:]=[a[3],a[1]]
        items=root.find(x.Q+'ChildItems');items[:]=[items[4],items[1]]
        changed=x.interface(x.convert(raw,E.tostring(root,encoding='unicode'),paths=x.object_paths(self.owner(r),'Catalog'),object_name='XML_Catalog'))
        self.assertEqual([s.val(a[3]) for a in changed[3][2:4]],['Flag','Object'])
        self.assertEqual(s.val(changed[3][1]),'2');self.assertEqual(s.val(changed[2]),'// mixed')

    def owner(self,r):
        _,pos=s.read_record(base64.b64decode(r['snapshot']),12)
        raw,_=s.read_record(base64.b64decode(r['snapshot']),pos)
        return s.Parser(s.inflate(raw).decode('utf-8-sig')).documents()[0]

    def test_mixed_attributes_reject_collisions_multiple_main_and_dangling_paths(self):
        r=creation.fixture()
        for case in ('name','id','main','dangling','unknown'):
            root=self.mixed_xml();attrs=root.find(x.Q+'Attributes')
            if case=='name':attrs[0].set('name','object')
            elif case=='id':attrs[0].set('id','1')
            elif case=='main':E.SubElement(attrs[0],x.Q+'MainAttribute').text='true'
            elif case=='dangling':attrs.remove(attrs[0])
            else:E.SubElement(attrs[0],x.Q+'Unknown').text='lost'
            with self.subTest(case=case),self.assertRaises(ValueError):
                managed_form_operations.create(dict(r,form_xml=E.tostring(root,encoding='unicode')))

    def test_change_packet_replaces_the_whole_mixed_attribute_collection(self):
        r=change.fixture()
        metadata=metadata_context.context_metadata(base64.b64decode(r['context']),r['object_id'])[0]
        parent=external_data.extract(base64.b64decode(r['storage']),s.val(metadata[3]))
        owner=s.Parser(s.inflate(base64.b64decode(parent['data'])).decode('utf-8-sig')).documents()[0]
        root=self.mixed_xml(s.val(owner[1][9][1][2]))
        form=x.interface(extra(managed_form_operations.change(dict(r,form_xml=E.tostring(root,encoding='unicode')))))
        self.assertEqual(s.val(form[3][1]),'5')
        self.assertEqual([s.val(a[3]) for a in form[3][2:7]],['Message','Object','Amount','Flag','Moment'])
        self.assertEqual(s.val(form[3][3][5][1][1]),s.val(owner[1][1]))

    def test_document_main_and_additional_attributes_share_the_converter(self):
        from test_form_kinds_xml import native,document_paths
        root=self.mixed_xml('Doc');root.remove(root.find(x.Q+'UseForFoldersAndItems'))
        main=next(a for a in root.find(x.Q+'Attributes') if a.get('name')=='Object')
        main.find(x.Q+'Type/{'+x.CORE+'}Type').text='cfg:DocumentObject.Doc'
        for field in root.find(x.Q+'ChildItems')[:2]:
            node=field.find(x.Q+'DataPath');node.text=node.text.replace('Description','Date').replace('Code','Number')
        raw=x.convert(native('Document'),E.tostring(root,encoding='unicode'),paths=document_paths(),object_name='Doc',kind='Document')
        self.assertEqual(s.val(x.interface(raw)[3][1]),'5')

    def test_complete_list_reorders_removes_renames_and_replaces_module(self):
        r=change.fixture()
        parent=external_data.extract(base64.b64decode(r['storage']),s.val(metadata_context.context_metadata(base64.b64decode(r['context']),r['object_id'])[0][3]))
        owner=s.Parser(s.inflate(base64.b64decode(parent['data'])).decode('utf-8-sig')).documents()[0]
        name=s.val(owner[1][9][1][2])
        r.update(form_xml=xml(name,[('Renamed',2,'Description'),('AttributeField',20,'TestAttribute')]),
                 module_text='&AtClient\nProcedure Test()\n    Message("A & B");\nEndProcedure')
        f=x.interface(extra(managed_form_operations.change(r)));i,n,end=x.elements.form_collection(f)
        self.assertEqual(n,2)
        self.assertEqual([s.val(f[1][j+1][6]) for j in range(i+1,end,2)],['Renamed','AttributeField'])
        self.assertIn('Message("A & B")',s.val(f[2]));self.assertIn('\r\n',s.val(f[2]))
        self.assertIn('0,',s.render(f[1][end-1][11]))

    def test_creation_and_change_use_same_conversion(self):
        r=creation.fixture();r.update(form_xml=xml(),module_text='// identical module')
        result=managed_form_operations.create(r);native=extra(result)
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
                managed_form_operations.create(dict(r,form_xml=value))

    def test_native_auxiliary_names_and_omitted_or_empty_module(self):
        r=creation.fixture();r.update(form_xml=xml(),module_text='// preserved')
        native=extra(managed_form_operations.create(r))
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
