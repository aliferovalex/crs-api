"""Inline register fields and context-resolved cross-object references."""
import base64, copy, unittest
from xml.etree import ElementTree as E
import test_object_xml_profiles as fixture
import metadata_context
import metadata_identifiers
import xml_namespaces
import object_creation_serializer as c, metadata_object_xml as flat, native_metadata as s, type_description_xml as types

Q='{'+xml_namespaces.MD+'}';XR='{'+xml_namespaces.READABLE+'}'
IDS=['77777777-7777-4777-8777-777777777771','77777777-7777-4777-8777-777777777772','77777777-7777-4777-8777-777777777773']

def xml():
    root=E.fromstring(fixture.xml('InformationRegister'));children=root[0].find(Q+'ChildObjects')
    for tag,oid,name,pattern in zip(('Dimension','Resource','Attribute'),IDS,('Key','Amount','Note'),('{"Pattern",{"S",32,1}}','{"Pattern",{"N",15,2,0}}','{"Pattern",{"B"}}')):
        node=E.SubElement(children,Q+tag,uuid=oid);props=E.SubElement(node,Q+'Properties');E.SubElement(props,Q+'Name').text=name
        props.append(types.export(s.Parser(pattern).documents()[0],Q+'Type'))
    return E.tostring(root,encoding='unicode')

class RegisterProfileTests(unittest.TestCase):
    def test_all_inline_types_and_complete_packet_feature_map(self):
        r=fixture.request('InformationRegister');r['object_xml']=xml();r['modules']={'RecordSetModule':'// all records','ManagerModule':'// manager'}
        result=c.serialize(r);transport=s.inflate(base64.b64decode(result['data'])[18:]);_,pos=s.read_record(transport,0);storage,_=s.read_record(transport,pos+4)
        meta,pos=s.read_record(storage,12);body,pos=s.read_record(storage,pos);m=s.Parser(meta.decode('utf-8-sig')).documents()[0];native=s.Parser(s.inflate(body).decode('utf-8-sig')).documents()[0]
        self.assertEqual({s.val(v) for v in m[13][1:]},set(IDS));self.assertEqual({s.val(v) for v in m[11][1::2]},{fixture.OID+'.1',fixture.OID+'.2'})
        self.assertEqual([s.val(native[i][1]) for i in (3,4,7)],['1','1','1'])
        self.assertEqual(s.render(native[7][2][0][1][1][2]),'{"Pattern",{"B"}}')

    def test_inline_uuid_name_property_and_form_conflicts_reject(self):
        for case in ('uuid','name','property','form'):
            root=E.fromstring(xml());children=root[0].find(Q+'ChildObjects')
            if case=='uuid':children[1].set('uuid',IDS[0])
            elif case=='name':children[1][0][0].text='key'
            elif case=='property':E.SubElement(children[0][0],Q+'Master').text='true'
            else:E.SubElement(children,Q+'Form').text='NotSupported'
            with self.subTest(case=case),self.assertRaises(ValueError):flat.object_xml(E.tostring(root,encoding='unicode'),'8.5.1.1529','InformationRegister')

    def test_journal_references_resolve_to_instance_uuid(self):
        r=fixture.request('DocumentJournal');objects=metadata_context.context_objects(r['context']);template=copy.deepcopy(next(iter(objects.values())))
        template[0][1]=s.atom(IDS[0]);template[0][2]=s.atom(metadata_identifiers.class_id('Document'));template[0][9]=s.atom('TestDocument',True)
        root=E.fromstring(r['object_xml']);node=E.SubElement(root[0][0],Q+'RegisteredDocuments');E.SubElement(node,XR+'Item').text='Document.TestDocument';text=E.tostring(root,encoding='unicode')
        raw=flat.object_xml(text,'8.5.1.1529','DocumentJournal',{IDS[0]:template})[2];native=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.val(native[1][6][2][2][1]),IDS[0])
        with self.assertRaisesRegex(ValueError,'Missing'):flat.object_xml(text,'8.5.1.1529','DocumentJournal',{})
        with self.assertRaisesRegex(ValueError,'ambiguous'):flat.object_xml(text,'8.5.1.1529','DocumentJournal',{IDS[0]:template,IDS[1]:copy.deepcopy(template)})
        E.SubElement(node,XR+'Item').text='Document.TestDocument'
        with self.assertRaisesRegex(ValueError,'duplicate'):flat.object_xml(E.tostring(root,encoding='unicode'),'8.5.1.1529','DocumentJournal',{IDS[0]:template})

    def test_unknown_periodicity_write_mode_and_missing_documents_reject(self):
        for key,value in [('InformationRegisterPeriodicity','Unknown'),('WriteMode','Unknown')]:
            root=E.fromstring(xml());E.SubElement(root[0][0],Q+key).text=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'property'):flat.object_xml(E.tostring(root,encoding='unicode'),'8.5.1.1529','InformationRegister')
        with self.assertRaisesRegex(ValueError,'Required'):flat.object_xml(fixture.xml('DocumentJournal'),'8.5.1.1529','DocumentJournal')

    def test_accumulation_requires_numeric_resources_and_recorder_transaction(self):
        root=E.fromstring(fixture.xml('AccumulationRegister'));child=root[0].find(Q+'ChildObjects')
        node=E.SubElement(child,Q+'Resource',uuid=IDS[0]);props=E.SubElement(node,Q+'Properties');E.SubElement(props,Q+'Name').text='Amount'
        props.append(types.export(s.Parser('{"Pattern",{"N",15,2,0}}').documents()[0],Q+'Type'))
        text=E.tostring(root,encoding='unicode');raw=flat.object_xml(text,'8.5.1.1529','AccumulationRegister')[2]
        self.assertEqual(s.val(s.Parser(raw.decode('utf-8-sig')).documents()[0][5][1]),'1')
        props.remove(props.find(Q+'Type'));props.append(types.export(s.Parser('{"Pattern",{"B"}}').documents()[0],Q+'Type'))
        with self.assertRaisesRegex(ValueError,'scalar type'):flat.object_xml(E.tostring(root,encoding='unicode'),'8.5.1.1529','AccumulationRegister')
        r=fixture.request('AccumulationRegister');r['object_xml']=text
        with self.assertRaisesRegex(ValueError,'recorder'):c.serialize(r)

if __name__=='__main__':unittest.main()
