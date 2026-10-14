"""Shared creation path for independently verified metadata families."""
import base64,hashlib,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import object_xml_profiles as profiles,flat_object_serializer as flat,constant_serializer as c,metadata_serializer as s
import test_catalog_creation_full_xml as fixture

PATHS={'DataProcessor':[1,3,1],'Report':[1,3,1],'Subsystem':[1,1],'Role':[1,1],
       'CommandGroup':[1,6],'SessionParameter':[1,1,1],'HTTPService':[1,2],'WebService':[1,2]}
OID='88888888-8888-4888-8888-888888888888'


def xml(kind):
    root=E.Element('{'+c.MD+'}MetaDataObject',version='2.21');obj=E.SubElement(root,'{'+c.MD+'}'+kind,uuid=OID)
    props=E.SubElement(obj,'{'+c.MD+'}Properties')
    for key,value in [('Name','ProfileTest'),('Comment','Whole XML " & text')]:E.SubElement(props,'{'+c.MD+'}'+key).text=value
    if kind=='HTTPService':E.SubElement(props,'{'+c.MD+'}RootURL').text='another-route'
    if kind=='WebService':E.SubElement(props,'{'+c.MD+'}Namespace').text='urn:another-service'
    E.SubElement(obj,'{'+c.MD+'}ChildObjects')
    return E.tostring(root,encoding='unicode')


def request(kind):
    r=fixture.request(xml('DataProcessor'));rid=r['object_id'];data=base64.b64decode(r['snapshots'][rid]);meta,pos=s.read_record(data,12);content,pos=s.read_record(data,pos)
    raw=s.inflate(content).decode('utf-8-sig').replace(c.identifiers.class_id('Catalog'),c.identifiers.class_id(kind));body=s.compress(b'\xef\xbb\xbf'+raw.encode('utf-8'))
    m=s.Parser(meta.decode('utf-8-sig')).documents()[0]
    manifest=s.text_bytes([[s.atom(0),s.atom(1),m[1],s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(body).hexdigest(),True),s.atom(0)]])
    r['snapshots'][rid]=base64.b64encode(s.storage([meta,body],manifest)).decode();r['object_type']=kind;r[kind.lower()+'_xml']=xml(kind)
    return r


class ObjectProfileTests(unittest.TestCase):
    def test_processor_and_report_properties_match_complete_native_objects(self):
        import v8unpack_backend as backend
        for kind in ('DataProcessor','Report'):
            data=json.loads(Path(__file__).with_name('fixtures').joinpath(kind.lower()+'_properties_851.json').read_text(encoding='utf-8'))
            for case in data['cases']:
                with self.subTest(kind=kind,case=case['name']):
                    raw=flat.object_xml(case['xml'],'8.5.1.1529',kind)[2]
                    self.assertEqual(backend.signature(s.Parser(raw.decode('utf-8-sig')).documents()),backend.signature(s.Parser(case['body']).documents()))

    def test_all_families_share_identity_and_complete_body_conversion(self):
        for kind,path in PATHS.items():
            with self.subTest(kind=kind):
                oid,name,raw,ids=flat.object_xml(xml(kind),'8.5.1.1529',kind);node=s.Parser(raw.decode('utf-8-sig')).documents()[0]
                for index in path:node=node[index]
                self.assertEqual((s.val(node[1][2]),s.val(node[2]),s.val(node[4])),(OID,'ProfileTest','Whole XML " & text'))
                self.assertEqual(len(ids),4 if kind in ('DataProcessor','Report') else 0)
                result=c.serialize(request(kind));self.assertEqual(result['object_id'],OID)
                transport=s.inflate(base64.b64decode(result['data'])[18:]);_,pos=s.read_record(transport,0);storage,_=s.read_record(transport,pos+4);s.validate_storage(storage)

    def test_required_service_strings_and_scalar_type(self):
        for kind in ('HTTPService','WebService'):
            body=s.Parser(flat.object_xml(xml(kind),'8.5.1.1529',kind)[2].decode('utf-8-sig')).documents()[0]
            self.assertEqual(s.val(body[1][1]),'another-route' if kind=='HTTPService' else 'urn:another-service')
        import type_description_xml as t
        root=E.fromstring(xml('SessionParameter'));props=root[0][0]
        props.append(t.export(s.Parser('{"Pattern",{"N",20,5,1}}').documents()[0],'{'+c.MD+'}Type'))
        body=s.Parser(flat.object_xml(E.tostring(root,encoding='unicode'),'8.5.1.1529','SessionParameter')[2].decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.render(body[1][1][2]),'{"Pattern",{"N",20,5,1}}')
        for kind,key in [('HTTPService','RootURL'),('WebService','Namespace')]:
            root=E.fromstring(xml(kind));root[0][0].remove(root[0][0].find('{'+c.MD+'}'+key))
            with self.assertRaisesRegex(ValueError,'Required'):flat.object_xml(E.tostring(root,encoding='unicode'),'8.5.1.1529',kind)

    def test_modules_are_independent_complete_external_streams(self):
        for kind in ('DataProcessor','Report'):
            r=request(kind);r['modules']={'ObjectModule':'// object','ManagerModule':'// manager'};result=c.serialize(r)
            self.assertEqual({row['name'] for row in result['externals']},{OID+'.0',OID+'.2'})
            self.assertTrue(all(row['action']==1 for row in result['externals']))
            transport=s.inflate(base64.b64decode(result['data'])[18:]);_,pos=s.read_record(transport,0);storage,_=s.read_record(transport,pos+4)
            metadata,pos=s.read_record(storage,12);m=s.Parser(metadata.decode('utf-8-sig')).documents()[0]
            self.assertEqual(s.val(m[11][0]),'2');self.assertEqual({s.val(n) for n in m[11][1::2]},{OID+'.0',OID+'.2'})
        r=request('DataProcessor');r['modules']={'Unknown':'// lost'}
        with self.assertRaisesRegex(ValueError,'module files'):c.serialize(r)

    def test_unimplemented_children_and_nondefault_properties_are_rejected(self):
        for kind in PATHS:
            root=E.fromstring(xml(kind));E.SubElement(root[0].find('{'+c.MD+'}ChildObjects'),'{'+c.MD+'}Form').text='Unsupported'
            error='child reference' if kind in ('DataProcessor','Report') else 'children'
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,error):flat.object_xml(E.tostring(root,encoding='unicode'),'8.5.1.1529',kind)
        root=E.fromstring(xml('DataProcessor'));E.SubElement(root[0][0],'{'+c.MD+'}DefaultForm').text='DataProcessor.ProfileTest.Form.Unknown'
        with self.assertRaisesRegex(ValueError,'form owner'):flat.object_xml(E.tostring(root,encoding='unicode'),'8.5.1.1529','DataProcessor')


if __name__=='__main__':unittest.main()
