"""Existing children survive whole parent edits; missing refs cannot erase them."""
import base64,copy,unittest
from xml.etree import ElementTree as E
import xml_namespaces
import native_metadata as s
import object_change_serializer as change
import test_document_serializer as document
import test_object_change_serializer as snapshots
from test_managed_form_creation import store

FID='99999999-9999-4999-8999-999999999999'


def fixture(omitted_snapshot_map=False):
    request,docs,raw=snapshots.fixture('Document',document.xml());oid=request['object_id'];cls=change.ids.class_id('DocumentForm')
    body=s.Parser(raw.decode('utf-8-sig')).documents();body[0][7]=[s.atom(cls),s.atom(1),s.atom(FID)]
    docs[0][12]=[s.atom(1),[s.atom(cls),s.atom(1),s.atom(FID)]]
    form=copy.deepcopy(docs);form[0][1],form[0][2],form[0][3],form[0][9],form[0][10]=s.atom(FID),s.atom(cls),s.atom(oid),s.atom('StoredForm',True),s.atom(0);form[0][12]=[s.atom(0)]
    saved=copy.deepcopy(docs)
    if omitted_snapshot_map:saved[0][12]=[s.atom(0)]
    request['snapshot']=store(saved,s.native_body_bytes(body))
    request['context']=base64.b64encode(s.storage([s.text_bytes(docs),s.text_bytes(form)],s.text_bytes([[s.atom(0)]]))).decode()
    tree=E.fromstring(request['object_xml']);E.SubElement(tree[0].find('{'+xml_namespaces.MD+'}ChildObjects'),'{'+xml_namespaces.MD+'}Form').text='StoredForm'
    request['object_xml']=E.tostring(tree,encoding='unicode')
    return request,docs,form


class ChildObjectTests(unittest.TestCase):
    def test_parent_change_preserves_existing_children_with_or_without_snapshot_map(self):
        for omitted in (False,True):
            request,source,_=fixture(omitted);request['object_xml']=request['object_xml'].replace('Document test','Changed parent')
            _,docs,raw,_,_=snapshots.unpack(change.serialize(request));body=s.Parser(raw.decode('utf-8-sig')).documents()[0]
            self.assertEqual(s.val(body[7][2]),FID);self.assertEqual(s.render(docs[0][12]),s.render(source[0][12]))
            self.assertIn('Changed parent',raw.decode('utf-8-sig'))

    def test_deleted_duplicated_or_foreign_reference_rejected(self):
        for action in ('remove','duplicate','unknown'):
            request,_,_=fixture();root=E.fromstring(request['object_xml']);children=root[0].find('{'+xml_namespaces.MD+'}ChildObjects')
            if action=='remove':children.remove(children[0])
            elif action=='duplicate':children.append(copy.deepcopy(children[0]))
            else:children[0].text='AnotherForm'
            request['object_xml']=E.tostring(root,encoding='unicode')
            with self.subTest(action=action),self.assertRaises(ValueError):change.serialize(request)

    def test_incorrect_position_or_parent_rejected(self):
        for slot,value in ((10,s.atom(-1)),(3,s.atom(s.ZERO)),(4,s.atom(FID))):
            request,docs,form=fixture();form[0][slot]=value
            request['context']=base64.b64encode(s.storage([s.text_bytes(docs),s.text_bytes(form)],s.text_bytes([[s.atom(0)]]))).decode()
            with self.subTest(slot=slot),self.assertRaises(ValueError):change.serialize(request)

    def test_position_gaps_after_native_deletion_are_valid(self):
        request,docs,form=fixture();form[0][10]=s.atom(1)
        request['context']=base64.b64encode(s.storage([s.text_bytes(docs),s.text_bytes(form)],s.text_bytes([[s.atom(0)]]))).decode()
        self.assertIn('request_xml',change.serialize(request))


if __name__=='__main__':unittest.main()
