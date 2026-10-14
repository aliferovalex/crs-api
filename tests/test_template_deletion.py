"""Template deletion shares the native graph while preserving owner contents."""
import base64
import copy
import json
import sys
import unittest
import uuid
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('delete_owned_object_serializer.py')).parent))
import delete_owned_object_serializer as deletion
import metadata_serializer as s
import constant_serializer as c
from test_managed_form_serializer import store


def unpack(result):
    raw=s.inflate(base64.b64decode(result['data'])[18:]);graph,pos=s.read_record(raw,0);storage,_=s.read_record(raw,pos+4)
    s.validate_storage(storage);meta,pos=s.read_record(storage,12);body,_=s.read_record(storage,pos)
    return s.Parser(graph.decode('utf-8-sig')).documents()[0],s.Parser(meta.decode('utf-8-sig')).documents(),s.inflate(body)


class TemplateDeletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=json.loads(Path(__file__).with_name('fixtures').joinpath('template_deletion_851.json').read_text(encoding='utf-8'))

    def test_native_parent_and_inactive_deleted_descriptor(self):
        r=copy.deepcopy(self.fixture['request']);result=deletion.serialize(r);graph,docs,body=unpack(result)
        self.assertEqual(s.render(s.Parser(body.decode('utf-8-sig')).documents()),s.render(s.Parser(self.fixture['parent_body']).documents()))
        pairs=c.children(docs[0]);source=c.context_objects(r['context'])
        self.assertEqual(set(pairs),set(c.children(source[result['parent_id']][0]))-{(r['form_id'],c.identifiers.class_id('Template'))})
        flags={s.val(graph[4][i]):s.val(graph[4][i+1]) for i in range(1,len(graph[4]),2)}
        self.assertEqual(flags[r['form_id']],'0')
        self.assertNotIn(r['form_id'],[row['id'] for row in result['descriptions']])

    def test_selected_schema_is_rejected(self):
        r=copy.deepcopy(self.fixture['request']);oid=self.fixture['selected_id'];objects=c.context_objects(r['context']);m=objects[oid][0]
        r.update(form_id=oid,form_original_version=uuid.UUID(s.val(m[7])).bytes_le.hex()+'00000000',form_snapshot=store(objects[oid],b'not emitted'))
        with self.assertRaisesRegex(ValueError,'selected by an owner reference'):deletion.serialize(r)

    def test_stale_child_and_unrelated_parent_edits_are_rejected(self):
        r=copy.deepcopy(self.fixture['request'])
        with self.assertRaisesRegex(ValueError,'source version'):deletion.serialize(dict(r,form_original_version='f'*40))
        root=E.fromstring(r['object_xml']);root.find('.//{'+c.MD+'}Comment').text='unrelated change'
        with self.assertRaisesRegex(ValueError,'preserve all other'):deletion.serialize(dict(r,object_xml=E.tostring(root,encoding='unicode')))

    def test_catalog_template_deletion_preserves_attributes_and_form(self):
        import test_delete_form_serializer as forms
        r,source=forms.fixture();objects=c.context_objects(r['context']);parent=c.guid(s.val(objects[r['form_id']][0][3]));oid='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';cls=c.identifiers.class_id('Template')
        child=copy.deepcopy(objects[r['form_id']]);child[0][1]=s.atom(oid);child[0][2]=s.atom(cls);child[0][9]=s.atom('Layout',True)
        owner=objects[parent];owner[0][12][0]=s.atom(2);owner[0][12].append([s.atom(cls),s.atom(1),s.atom(oid)])
        source[3]=[s.atom(cls),s.atom(1),s.atom(oid)];r['snapshot']=store(owner,s.native_body_bytes([source]));r['context']=base64.b64encode(s.storage([s.text_bytes(v) for v in list(objects.values())+[child]],s.text_bytes([[s.atom(0)]]))).decode()
        root=E.fromstring(r['object_xml']);E.SubElement(root[0].find('{'+c.MD+'}ChildObjects'),'{'+c.MD+'}Form').text=s.val(objects[r['form_id']][0][9])
        form_request=copy.deepcopy(r);form_root=E.fromstring(form_request['object_xml'])
        E.SubElement(form_root[0].find('{'+c.MD+'}ChildObjects'),'{'+c.MD+'}Template').text='Layout'
        form_request['object_xml']=E.tostring(form_root,encoding='unicode')
        _,_,form_body=unpack(deletion.serialize(form_request));without_form=s.Parser(form_body.decode('utf-8-sig')).documents()[0]
        kept_template=copy.deepcopy(source);kept_template[7]=[source[7][0],s.atom(0)]
        self.assertEqual(s.render(without_form),s.render(kept_template))
        r.update(form_id=oid,form_snapshot=store(child,b'unused deleted layout'),object_xml=E.tostring(root,encoding='unicode'))
        _,_,body=unpack(deletion.serialize(r));after=s.Parser(body.decode('utf-8-sig')).documents()[0]
        expected=copy.deepcopy(source);expected[3]=[s.atom(cls),s.atom(0)]
        self.assertEqual(s.render(after),s.render(expected))


if __name__=='__main__':unittest.main()
