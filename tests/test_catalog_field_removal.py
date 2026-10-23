"""Field removal depends on actual final form bindings, not form existence."""
import base64,copy,json,unittest,uuid
from xml.etree import ElementTree as E
import test_catalog_attribute_serializer as attributes
from test_managed_form_creation import store
import managed_form_operations as operations
import metadata_context
import metadata_identifiers as ids
import metadata_object_xml as metadata
import native_metadata as s
import native_version_fixture
import object_change_serializer as changes


def interface(path):
    q='{http://v8.1c.ru/8.3/xcf/logform}';core='{http://v8.1c.ru/8.1/data/core}'
    root=E.Element(q+'Form',version='2.21');E.SubElement(root,q+'AutoCommandBar',name='FormCommandBar',id='-1')
    E.SubElement(root,q+'UseForFoldersAndItems').text='Items'
    field=E.SubElement(E.SubElement(root,q+'ChildItems'),q+'InputField',name='BoundField',id='1');E.SubElement(field,q+'DataPath').text=path
    attr=E.SubElement(E.SubElement(root,q+'Attributes'),q+'Attribute',name='Object',id='17')
    E.SubElement(E.SubElement(attr,q+'Type'),core+'Type').text='cfg:CatalogObject.'+'CATALOG_NAME'
    E.SubElement(attr,q+'MainAttribute').text='true';return root


class CatalogFieldRemovalTests(unittest.TestCase):
    def fixture(self,used):
        request=attributes.fixture();compiled=changes.serialize(request,native_content=True);owner=request['object_id'];objects=metadata_context.context_objects(request['context'])
        objects[owner]=compiled.docs;native=s.Parser(compiled.body.decode('utf-8-sig')).documents()[0];fid=str(uuid.uuid4());formname='Main'
        native[7]=[native[7][0],s.atom(1),s.atom(fid)];objects[owner][0][12]=[s.atom(1),[s.atom(ids.class_id('CatalogForm')),s.atom(1),s.atom(fid)]]
        name=s.val(objects[owner][0][9]);form=interface('Object.TestAttribute' if used else 'Object.Code')
        xml=E.tostring(form,encoding='unicode').replace('CATALOG_NAME',name)
        definition=E.Element(metadata.Q+'MetaDataObject',version='2.21');node=E.SubElement(definition,metadata.Q+'Form',uuid=fid);E.SubElement(E.SubElement(node,metadata.Q+'Properties'),metadata.Q+'Name').text=formname
        _,formbody,external=operations.create_native('Catalog',formname,request['platform'],native,E.tostring(definition,encoding='unicode'),xml,'// source')
        docs=copy.deepcopy(objects[owner]);m=docs[0];m[1],m[2],m[3],m[9]=s.atom(fid),s.atom(ids.class_id('CatalogForm')),s.atom(owner),s.atom(formname,True)
        m[12]=m[13]=[s.atom(0)];m[14]=[s.atom(1),s.atom(owner),s.atom(1)];m[11]=[s.atom(1),s.atom(fid+'.0',True),s.atom(str(uuid.uuid4()))];objects[fid]=docs
        body=s.native_body_bytes([native]);request['snapshot']=store(objects[owner],body)
        request['context']=base64.b64encode(s.storage([s.text_bytes(d) for d in objects.values()],s.text_bytes([[s.atom(0)]]))).decode()
        request['storage']=native_version_fixture.storage(objects,{owner:body,fid:formbody},{fid+'.0':external})
        top=metadata.export(native,{formname:fid},request['platform'],'Catalog');children=top[0].find(metadata.Q+'ChildObjects');children.remove(children.find(metadata.Q+'Attribute'))
        request['object_xml']=E.tostring(top,encoding='unicode');return request,fid

    def test_used_field_is_rejected_before_single_object_packet_is_built(self):
        request,_=self.fixture(True)
        with self.assertRaisesRegex(ValueError,'Final external stream references deleted metadata'):changes.serialize(request)

    def test_unused_field_can_be_removed_with_a_retained_form(self):
        request,fid=self.fixture(False);result=changes.serialize(request)
        _,docs,body,_,_=__import__('test_object_change_serializer').unpack(result)
        self.assertEqual(s.render(docs[0][13]),'{0}');self.assertIn(fid,[oid for oid,cls in metadata_context.children(docs[0])])
        self.assertEqual(s.val(s.Parser(body.decode('utf-8-sig')).documents()[0][6][1]),'0')

    def test_removing_a_field_requires_source_streams_when_forms_exist(self):
        request,_=self.fixture(False);request.pop('storage')
        with self.assertRaisesRegex(ValueError,'require current version storage'):changes.serialize(request)


if __name__=='__main__':unittest.main()
