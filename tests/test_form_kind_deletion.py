"""Deletion shares the packet graph across Document and Configuration parents."""
import base64,copy,json,unittest,uuid
from pathlib import Path
from xml.etree import ElementTree as E
import configuration_xml
import metadata_context
import xml_namespaces
import metadata_common_xml
import native_metadata as s
import delete_object_serializer as deletion
import test_child_object_xml as children
import test_object_creation_serializer as roots
from test_managed_form_creation import store

Q='{'+xml_namespaces.MD+'}'


def fixture(kind):
    if kind=='DocumentForm':
        request,parent,form=children.fixture();objects=metadata_context.context_objects(request['context']);tree=E.fromstring(request['object_xml']);tree[0].find(Q+'ChildObjects').clear();snapshot=request['snapshot'];fid=children.FID;parent_id=request['object_id']
        data=base64.b64decode(snapshot);_,pos=s.read_record(data,12);body,_=s.read_record(data,pos);native=s.Parser(s.inflate(body).decode('utf-8-sig')).documents()[0][1];layout=json.loads(Path(deletion.__file__).with_name('document_layout_851.json').read_text(encoding='utf-8'))
        info=E.SubElement(tree[0],Q+'InternalInfo');xr='{'+xml_namespaces.READABLE+'}'
        for index,category in enumerate(('Object','Ref','Selection','List','Manager')):
            typ=E.SubElement(info,xr+'GeneratedType',name='Document'+category+'.XML_Document',category=category)
            for tag,slot in zip(('TypeId','ValueId'),layout['generated_slots'][index*2:index*2+2]):E.SubElement(typ,xr+tag).text=s.val(native[slot])
        xml=E.tostring(tree,encoding='unicode')
    else:
        r=roots.fixture('8.5.1.1529');objects=metadata_context.context_objects(r['context']);parent_id=r['object_id'];parent=objects[parent_id];fid=children.FID;cls=deletion.ids.class_id('CommonForm')
        source=base64.b64decode(r['snapshots'][parent_id]);_,pos=s.read_record(source,12);body,_=s.read_record(source,pos);docs=s.Parser(s.inflate(body).decode('utf-8-sig')).documents();docs[0].append([s.atom(cls),s.atom(1),s.atom(fid)])
        parent[0][12][0]=s.atom(len(parent[0][12]));parent[0][12].append([s.atom(cls),s.atom(1),s.atom(fid)])
        form=copy.deepcopy(parent);form[0][1],form[0][2],form[0][3],form[0][9],form[0][10]=s.atom(fid),s.atom(cls),s.atom(parent_id),s.atom('StoredForm',True),s.atom(0);form[0][11]=form[0][12]=form[0][13]=[s.atom(0)];form[0][14]=[s.atom(1),s.atom(parent_id),s.atom(1)];form[2]=[s.atom(0)];objects[fid]=form
        # Synthetic root fixture lacked its Language collection in the body.
        # The editor checks every stored collection, including unchanged ones.
        for child_class in {cls for oid,cls in metadata_context.children(parent[0]) if cls!=deletion.ids.class_id('CommonForm')}:
            keys=[oid for oid,cls in metadata_context.children(parent[0]) if cls==child_class]
            docs[0].append([s.atom(child_class),s.atom(len(keys))]+[s.atom(oid) for oid in keys])
        snapshot=store(parent,s.native_body_bytes(docs));common=configuration_xml.common_properties(docs,parent_id,r['platform'])
        tree=E.Element(Q+'MetaDataObject',version='2.21');obj=E.SubElement(tree,Q+'Configuration',uuid=parent_id);props=E.SubElement(obj,Q+'Properties');metadata_common_xml.write(props, common);child=E.SubElement(obj,Q+'ChildObjects')
        for oid,cls in metadata_context.children(parent[0]):
            if oid!=fid:E.SubElement(child,Q+deletion.ids.class_labels()[cls]).text=s.val(objects[oid][0][9])
        xml=E.tostring(tree,encoding='unicode')
    layout=json.loads(Path(deletion.__file__).with_name('document_form_layout_851.json' if kind=='DocumentForm' else 'common_form_layout_851.json').read_text(encoding='utf-8'))
    body=s.Parser(layout['body_template']).documents();body[0][1][1][1][1][2]=s.atom(fid);body[0][1][1][1][2]=s.atom('StoredForm',True)
    return dict(platform='8.5.1.1529',form_id=fid,original_version=uuid.UUID(s.val(parent[0][7])).bytes_le.hex()+'00000000',form_original_version=uuid.UUID(s.val(form[0][7])).bytes_le.hex()+'00000000',snapshot=snapshot,form_snapshot=store(form,s.native_body_bytes(body)),context=base64.b64encode(s.storage([s.text_bytes(d) for d in objects.values()],s.text_bytes([[s.atom(0)]]))).decode(),object_xml=xml)


class FormKindDeletionTests(unittest.TestCase):
    def test_both_parent_kinds_remove_only_the_requested_form(self):
        for kind in ('DocumentForm','CommonForm'):
            request=fixture(kind);result=deletion.serialize(request)
            self.assertEqual(result['object_id'],children.FID);self.assertNotIn(children.FID,{item['id'] for item in result['descriptions']})
            raw=s.inflate(base64.b64decode(result['data'])[18:]);graph,pos=s.read_record(raw,0);storage,_=s.read_record(raw,pos+4);meta,pos=s.read_record(storage,12);body,_=s.read_record(storage,pos)
            docs=s.Parser(meta.decode('utf-8-sig')).documents();self.assertNotIn(children.FID,s.render(docs[0][12]));self.assertNotIn(children.FID,s.inflate(body).decode('utf-8-sig'))

    def test_unrelated_parent_properties_and_retained_reference_reject(self):
        for kind in ('DocumentForm','CommonForm'):
            for action in ('comment','reference'):
                request=fixture(kind);root=E.fromstring(request['object_xml'])
                if action=='comment':root[0].find(Q+'Properties/'+Q+'Comment').text='Unrelated change'
                else:E.SubElement(root[0].find(Q+'ChildObjects'),Q+('Form' if kind=='DocumentForm' else 'CommonForm')).text='StoredForm'
                request['object_xml']=E.tostring(root,encoding='unicode')
                with self.subTest(kind=kind,action=action),self.assertRaises(ValueError):deletion.serialize(request)


if __name__=='__main__':unittest.main()
