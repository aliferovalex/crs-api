"""A new register and its whole recorder XML form one coherent change."""
import copy, unittest
from xml.etree import ElementTree as E
import test_object_xml_profiles as fixture
import metadata_object_xml as flat, related_object_changes as related, native_metadata as s

import metadata_context
import metadata_identifiers
import xml_namespaces
Q='{'+xml_namespaces.MD+'}';XR='{'+xml_namespaces.READABLE+'}'
DOC='77777777-7777-4777-8777-777777777771';REG='77777777-7777-4777-8777-777777777772';OLD='77777777-7777-4777-8777-777777777773'

def input():
    r=fixture.request('Document');objects=metadata_context.context_objects(r['context']);rid=r['object_id'];template=objects[rid]
    for oid,kind,name in [(DOC,'Document','Recorder'),(REG,'AccumulationRegister','NewRegister'),(OLD,'InformationRegister','ExistingRegister')]:
        d=copy.deepcopy(template);m=d[0];m[1]=s.atom(oid);m[2]=s.atom(metadata_identifiers.class_id(kind));m[3]=s.atom(rid);m[9]=s.atom(name,True);m[12]=[s.atom(0)];m[14]=[s.atom(1),s.atom(rid),s.atom(1)];objects[oid]=d
    top=E.fromstring(fixture.xml('Document'));obj=top[0];obj.set('uuid',DOC);obj[0].find(Q+'Name').text='Recorder'
    records=E.SubElement(obj[0],Q+'RegisterRecords');E.SubElement(records,XR+'Item').text='InformationRegister.ExistingRegister'
    _,_,raw,ids=flat.object_xml(E.tostring(top,encoding='unicode'),'8.5.1.1529','Document',objects)
    internal=E.SubElement(obj,Q+'InternalInfo')
    for i,category in enumerate(('Object','Ref','Selection','List','Manager')):
        node=E.SubElement(internal,XR+'GeneratedType',name='Document'+category+'.Recorder',category=category)
        E.SubElement(node,XR+'TypeId').text=ids[i*2];E.SubElement(node,XR+'ValueId').text=ids[i*2+1]
    E.SubElement(records,XR+'Item').text='AccumulationRegister.NewRegister'
    r['related_objects']=[dict(kind='Document',object_id=DOC,object_xml=E.tostring(top,encoding='unicode'))]
    return r,objects,{DOC:raw},{DOC:bytes(20)}

class RelatedObjectTests(unittest.TestCase):
    def test_whole_recorder_references_body_and_dependency_version_change(self):
        r,objects,raws,versions=input();before=raws[DOC];changed=related.apply(r,objects,raws,versions,REG,'AccumulationRegister')
        self.assertEqual(changed,[DOC]);self.assertNotEqual(raws[DOC],before);self.assertNotEqual(versions[DOC],bytes(20))
        self.assertEqual(s.metadata_relations(objects[DOC][0][14])[REG],0)
        body=s.Parser(raws[DOC].decode('utf-8-sig')).documents()[0];self.assertEqual([s.val(n[2][1]) for n in body[1][24][2:]],[OLD,REG])

    def test_missing_new_link_removal_duplicate_and_identity_reject(self):
        for case in ('missing','remove','duplicate','identity','class','unsupported_source'):
            r,objects,raws,versions=input();entry=r['related_objects'][0];top=E.fromstring(entry['object_xml']);records=top[0][0].find(Q+'RegisterRecords')
            if case=='missing':records.remove(records[1])
            elif case=='remove':records.remove(records[0])
            elif case=='duplicate':r['related_objects'].append(copy.deepcopy(entry))
            elif case=='identity':entry['object_id']=OLD
            elif case=='class':entry['kind']='Catalog'
            else:
                source=s.Parser(raws[DOC].decode('utf-8-sig')).documents()[0];source[1][12]=s.atom(10);raws[DOC]=s.native_body_bytes([source])
            entry['object_xml']=E.tostring(top,encoding='unicode')
            with self.subTest(case=case),self.assertRaises(ValueError):related.apply(r,objects,raws,versions,REG,'AccumulationRegister')

    def test_primary_policy_requires_recorders_and_rejects_unrelated_changes(self):
        r,objects,raws,versions=input()
        with self.assertRaisesRegex(ValueError,'Unsupported'):related.apply(r,objects,raws,versions,REG,'InformationRegister')
        r['related_objects']=[]
        with self.assertRaisesRegex(ValueError,'requires'):related.apply(r,objects,raws,versions,REG,'AccumulationRegister')

if __name__=='__main__':unittest.main()
