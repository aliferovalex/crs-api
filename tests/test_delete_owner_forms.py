"""Deletion preserves owner streams and refuses selected owned forms."""
import base64
import copy
import hashlib
import json
import re
import sys
import unittest
import uuid
from pathlib import Path
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('delete_owned_object_serializer.py')).parent))
import metadata_serializer as s
import delete_owned_object_serializer as delete
import test_owner_forms as owners
import test_managed_form_change as catalog_form


def storage(docs,body,payloads=()):
    meta=s.text_bytes(docs);compressed=s.compress(body)
    manifest=[s.atom(0),s.atom(1),docs[0][1],s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(compressed).hexdigest(),True),s.atom(len(payloads))]
    for name,data in payloads:manifest.extend([s.atom(name,True),s.atom(hashlib.sha1(data).hexdigest(),True)])
    return base64.b64encode(s.storage([meta,compressed]+[data for _,data in payloads],s.text_bytes([manifest]))).decode()


def request(case):
    r=owners.request(case,externals=True)
    parent=s.context_metadata(base64.b64decode(r['context']),case['owner_id']);m=parent[0]
    m[12]=[s.atom(1),[s.atom(delete.ids.class_id(case['kind']+'Form')),s.atom(1),s.atom(case['form_id'])]]
    base=catalog_form.fixture();fd=s.context_metadata(base64.b64decode(base['context']),catalog_form.FID);fm=fd[0]
    fm[1]=s.atom(case['form_id']);fm[2]=s.atom(delete.ids.class_id(case['kind']+'Form'));fm[3]=s.atom(case['owner_id']);fm[9]=s.atom(case['form_name'],True);fm[12]=fm[13]=[s.atom(0)];fm[14]=[s.atom(1),fm[3],s.atom(1)]
    name=case['form_id']+'.0';version=str(uuid.uuid4());fm[11]=[s.atom(1),s.atom(name,True),s.atom(version)];fd[2]=[s.atom(1),[s.atom(name,True),s.atom(version),s.atom(1)]]
    payloads=[(s.val(m[11][index]),s.compress(b'unchanged owner module')) for index in (1,3)]
    parent_snapshot=storage(parent,case['owner_body'].encode('utf-8'),payloads)
    form_snapshot=storage(fd,case['body'].encode('utf-8'),[(name,s.compress(case['external'].encode('utf-8')))])
    # The owner definition is preserved in the interface fixture's native export.
    reference_data=json.loads(Path(__file__).with_name('fixtures').joinpath('owner_form_references_851.json').read_text(encoding='utf-8'))
    text=next(item['xml'] for item in reference_data['cases'] if item['kind']==case['kind'])
    for key in ('DefaultForm','AuxiliaryForm'):text=re.sub('<'+key+'>.*?</'+key+'>','<'+key+'/>',text,flags=re.S)
    text=re.sub(r'<Form>.*?</Form>','',text,flags=re.S)
    return dict(platform='8.5.1.1529',form_id=case['form_id'],original_version=uuid.UUID(s.val(m[7])).bytes_le.hex()+'00000000',form_original_version=uuid.UUID(s.val(fm[7])).bytes_le.hex()+'00000000',snapshot=parent_snapshot,form_snapshot=form_snapshot,context=base64.b64encode(s.storage([s.text_bytes(parent),s.text_bytes(fd)],s.text_bytes([[s.atom(0)]]))).decode(),object_xml=text),parent


class DeleteOwnerFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=json.loads(Path(__file__).with_name('fixtures').joinpath('owner_forms_851.json').read_text(encoding='utf-8'))['cases']

    def test_deletion_retains_owner_module_versions_without_payloads(self):
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                r,parent=request(case);result=delete.serialize(r)
                transport=s.inflate(base64.b64decode(result['data'])[18:]);graph,pos=s.read_record(transport,0);packed,_=s.read_record(transport,pos+4)
                meta,pos=s.read_record(packed,12);body,_=s.read_record(packed,pos);docs=s.Parser(meta.decode('utf-8-sig')).documents()
                self.assertEqual(s.render(docs[0][12]),'{0}')
                self.assertEqual(s.render(docs[2]),'{0}')
                self.assertEqual(len(result['externals']),2)
                for index in (2,4):self.assertEqual(base64.b64decode(s.val(docs[0][11][index])),uuid.UUID(s.val(parent[0][11][index])).bytes_le+bytes(4))
                self.assertTrue(all(item['action']==0 and item['object_id']==case['owner_id'] for item in result['externals']))
                self.assertEqual(s.render(s.Parser(graph.decode('utf-8-sig')).documents()[0][7][2]),s.render(docs[0][11]))

    def test_selected_form_requires_clearing_reference_before_deletion(self):
        for case in self.cases:
            r,parent=request(case);body=s.Parser(case['owner_body']).documents()[0];body[1][4]=s.atom(case['form_id'])
            payloads=[(s.val(parent[0][11][i]),s.compress(b'unchanged owner module')) for i in (1,3)]
            r['snapshot']=storage(parent,s.native_body_bytes([body]),payloads)
            with self.assertRaisesRegex(ValueError,'selected by an owner reference'):delete.serialize(r)


if __name__=='__main__':unittest.main()
