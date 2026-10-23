"""Multiple existing XML changes share one graph, manifest and repository version."""
import base64, copy, sys, unittest, uuid
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('configuration_batch.py')).parent))
import configuration_batch as batch
import native_metadata as s
import packet_builder as p
import object_change_serializer as changes
from test_object_change_serializer import fixture


def member(result):
    call=E.fromstring(result['request_xml']);q='{'+s.NS+'}'
    encoded=call.find(q+'params/'+q+'data').text;_,records=batch.read_packet(encoded)
    descriptions=[];externals=[]
    for record in records:
        m=s.Parser(record.metadata.decode('utf-8-sig')).documents()[0]
        descriptions.append(p.description(m,base64.b64decode(s.val(m[7])),base64.b64decode(s.val(m[8]))))
    for entry in call.findall(q+'params/'+q+'changes/'+q+'value'):
        oid=entry.find(q+'first').get('value')
        for item in entry.findall(q+'second/'+q+'externals/'+q+'value'):
            detail=item.find(q+'second');sup=detail.find(q+'_super')
            externals.append(dict(object_id=oid,name=sup.find(q+'name').get('value'),version=sup.find(q+'verID').get('value'),action=int(detail.find(q+'action').get('value'))))
    return dict(data=encoded,descriptions=descriptions,externals=externals)


def case():
    results=[];sources=[]
    for index,kind in enumerate(('DataProcessor','Report')):
        r,docs,_=fixture(kind)
        if index:
            old=r['object_id'];new='99999999-9999-4999-8999-999999999999'
            r,docs,_=fixture(kind,r['object_xml'].replace(old,new))
        r['modules']={'ObjectModule':'// same payload for two owners'}
        r['repository_version']='44444444-4444-4444-8444-444444444444'
        root=E.fromstring(r['object_xml']);root.find('.//{http://v8.1c.ru/8.3/MDClasses}Comment').text='Batch change '+kind
        r['object_xml']=E.tostring(root,encoding='unicode')
        result=changes.serialize(r);results.append(member(result))
        source=p.description(docs[0],uuid.UUID(s.val(docs[0][7])).bytes_le+bytes(4),uuid.UUID(s.val(docs[0][8])).bytes_le+bytes(4))
        sources.append(dict(request_xml=result['request_xml'],source=source,version_number=7))
    request=dict(repository='Synthetic',platform='8.5.1.1529',repository_version=r['repository_version'],packets=results)
    return request,sources


class ConfigurationBatchTests(unittest.TestCase):
    def test_two_bodies_and_deduplicated_module_payload_have_one_graph(self):
        r,_=case();result=batch.serialize(r);graph,records=batch.read_packet(result['data'])
        self.assertEqual(len(records),2);self.assertEqual(s.val(graph[0][0]),'2')
        for index in (1,2,3,4,5,7,8,9):self.assertEqual(s.val(graph[index][0]),'2')
        self.assertEqual([d['id'] for d in result['descriptions']],[entry['descriptions'][0]['id'] for entry in r['packets']])
        self.assertEqual(len(result['externals']),2)
        self.assertEqual(records[0].externals[0][1],records[1].externals[0][1])
        for record in records:
            self.assertEqual(s.inflate(record.externals[0][1]),s.inflate(records[0].externals[0][1]))

    def test_bad_inputs_reject_duplicates_stale_descriptors_and_stream_actions(self):
        r,_=case()
        for action in ('duplicate','local','class','payload','action'):
            target=copy.deepcopy(r)
            if action=='duplicate':target['packets'][1]=target['packets'][0]
            elif action=='local':target['packets'][0]['descriptions'][0]['local']='f'*40
            elif action=='class':target['packets'][0]['descriptions'][0]['class_id']=s.ZERO
            elif action=='payload':target['packets'][0]['data']=target['packets'][0]['data'][:-4]+'AAAA'
            else:target['packets'][0]['externals'][0]['action']=0
            with self.subTest(action=action),self.assertRaises(ValueError):batch.serialize(target)

    def test_creation_deletion_and_changed_graph_cannot_be_concatenated(self):
        r,_=case();graph,records=batch.read_packet(r['packets'][0]['data'])
        for index,value in ((4,[s.atom(1),s.atom(records[0].object_id),s.atom(0)]),(10,s.atom(1)),(6,[s.atom(1),s.atom(records[0].object_id),[s.atom(0)]])):
            target=copy.deepcopy(r);changed=copy.deepcopy(graph);changed[index]=value
            target['packets'][0]['data']=base64.b64encode(p.assemble(changed,records)).decode()
            with self.subTest(index=index),self.assertRaises(ValueError):batch.serialize(target)


if __name__=='__main__':unittest.main()
