"""Deletion is an inactive graph object plus a full updated parent, not a body."""
import base64,copy,hashlib,unittest,uuid,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
from xml.etree import ElementTree as E
import metadata_serializer as s
import metadata_identifiers as ids
import external_data
import catalog_object_xml as catalog
import delete_form_serializer as deletion
import test_managed_form_change as forms
from test_managed_form_serializer import store


def fixture():
    r=forms.fixture();records,manifest=external_data.records(base64.b64decode(r['storage']))
    parent=s.val(manifest[2]);owner=s.Parser(records[s.val(manifest[3])].decode('utf-8-sig')).documents()
    body=s.Parser(s.inflate(records[s.val(manifest[4])]).decode('utf-8-sig')).documents()[0]
    owner[0][12]=[s.atom(1),[s.atom(ids.class_id('CatalogForm')),s.atom(1),s.atom(forms.FID)]]
    body[7]=[body[7][0],s.atom(1),s.atom(forms.FID)]
    fd=s.context_metadata(base64.b64decode(r['context']),forms.FID)
    context=s.storage([s.text_bytes(owner),s.text_bytes(fd)],s.text_bytes([[s.atom(0)]]))
    top=catalog.export(body,{'Form':forms.FID},r['platform']);children=top[0].find(catalog.Q+'ChildObjects')
    children.remove(children.find(catalog.Q+'Form'))
    return dict(platform=r['platform'],form_id=forms.FID,original_version=uuid.UUID(s.val(owner[0][7])).bytes_le.hex()+'00000000',
        form_original_version=r['original_version'],snapshot=store(owner,s.native_body_bytes([body])),form_snapshot=r['snapshot'],
        context=base64.b64encode(context).decode(),object_xml=E.tostring(top,encoding='unicode')),body


class DeleteFormTests(unittest.TestCase):
    def test_deletes_only_form_and_preserves_parent_attributes(self):
        r,previous=fixture();result=deletion.serialize(r)
        raw=s.inflate(base64.b64decode(result['data'])[18:]);graph,pos=s.read_record(raw,0);storage,_=s.read_record(raw,pos+4)
        s.validate_storage(storage);meta,pos=s.read_record(storage,12);data,_=s.read_record(storage,pos)
        docs=s.Parser(meta.decode('utf-8-sig')).documents();body=s.Parser(s.inflate(data).decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.val(body[7][1]),'0')
        self.assertEqual(s.render(previous[:7]),s.render(body[:7]))
        self.assertNotIn(forms.FID,s.render(docs[0][12]))
        self.assertEqual(s.render(docs[0][12]),'{0}')
        g=s.Parser(graph.decode('utf-8-sig')).documents()[0];active=g[4]
        self.assertEqual({s.val(active[i]):s.val(active[i+1]) for i in range(1,len(active),2)}[forms.FID],'0')
        self.assertNotIn(forms.FID,[d['id'] for d in result['descriptions']])
        self.assertEqual(result['externals'],[])

    def test_rejects_stale_form_and_unrelated_xml_changes(self):
        r,previous=fixture()
        for key,value in [('platform','8.5.4.1878'),('form_original_version','f'*40),('original_version','f'*40)]:
            with self.subTest(key=key),self.assertRaises(ValueError):deletion.serialize(dict(r,**{key:value}))
        for mutation in ('not-removed','property','attribute'):
            top=E.fromstring(r['object_xml'])
            if mutation=='not-removed':E.SubElement(top[0].find(catalog.Q+'ChildObjects'),catalog.Q+'Form').text='Form'
            elif mutation=='property':top[0].find(catalog.Q+'Properties/'+catalog.Q+'Comment').text='Unrelated'
            else:top[0].find(catalog.Q+'ChildObjects/'+catalog.Q+'Attribute/'+catalog.Q+'Properties/'+catalog.Q+'Comment').text='Unrelated'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):deletion.serialize(dict(r,object_xml=E.tostring(top,encoding='unicode')))


if __name__=='__main__':unittest.main()
