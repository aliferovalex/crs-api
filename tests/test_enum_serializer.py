"""Inline Enum values, generated UUIDs and creation graph regression checks."""
import base64,hashlib,unittest,xml.etree.ElementTree as E
import test_constant_serializer as const
import metadata_serializer as s
import constant_serializer as c
import enum_serializer as enum

V1='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
V2='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'

def xml():
    return ('<MetaDataObject xmlns="%s" version="2.21"><Enum uuid="%s">'
            '<Properties><Name>XML_Enum</Name><Comment>Enum test</Comment></Properties>'
            '<ChildObjects><EnumValue uuid="%s"><Properties><Name>First</Name><Color>auto</Color></Properties></EnumValue>'
            '<EnumValue uuid="%s"><Properties><Name>Second</Name></Properties></EnumValue></ChildObjects>'
            '</Enum></MetaDataObject>')%(c.MD,const.CID,V1,V2)

def fixture():
    request=const.fixture('8.5.1.1529');rid=request['object_id']
    data=base64.b64decode(request['snapshots'][rid]);meta,pos=s.read_record(data,12);body,pos=s.read_record(data,pos)
    docs=s.Parser(s.inflate(body).decode('utf-8-sig')).documents();docs[0].append([s.atom(c.identifiers.class_id('Enum')),s.atom(0)])
    body=s.compress(s.text_bytes(docs));m=s.Parser(meta.decode('utf-8-sig')).documents()[0]
    manifest=s.text_bytes([[s.atom(0),s.atom(1),m[1],s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(body).hexdigest(),True),s.atom(0)]])
    request['snapshots'][rid]=base64.b64encode(s.storage([meta,body],manifest)).decode()
    request.update(object_type='Enum',enum_xml=xml());return request

class EnumSerializerTests(unittest.TestCase):
    def test_inline_values_and_object_name(self):
        oid,name,body,ids=enum.enum_xml(xml())
        doc=s.Parser(body.decode('utf-8-sig')).documents()[0]
        self.assertEqual((oid,name),(const.CID,'XML_Enum'))
        self.assertEqual(len(ids),8)
        self.assertEqual([s.val(v[0][1][1][2]) for v in doc[-1][2:]],[V1,V2])
        self.assertEqual([s.val(v[0][1][2]) for v in doc[-1][2:]],['First','Second'])
        self.assertEqual(s.val(doc[-1][1]),'2')
        self.assertEqual([s.val(doc[1][i]) for i in (1,2,3,4,7,8)],ids[:6])

    def test_duplicate_ids_names_and_unsupported_properties(self):
        cases=[xml().replace(V2,V1),xml().replace(V2,const.CID),xml().replace('Second','first'),
               xml().replace('auto','red'),xml().replace('<Color>auto</Color>','<Unknown/>'),
               xml().replace('<Name>XML_Enum</Name>','<Name>XML_Enum</Name><InputByString/>'),
               xml().replace('EnumValue','Attribute'),xml().replace('<Name>First</Name>','<Name>First</Name><Name>Again</Name>')]
        for text in cases:
            with self.subTest(text=text),self.assertRaises(ValueError):enum.enum_xml(text)

    def test_empty_values_and_legacy_profile(self):
        root=E.fromstring(xml());root[0].remove(root[0].find('{%s}ChildObjects'%c.MD))
        oid,name,body,ids=enum.enum_xml(E.tostring(root,encoding='unicode'),'8.3.27.2342')
        self.assertEqual(len(ids),6)
        self.assertEqual(s.val(s.Parser(body.decode('utf-8-sig')).documents()[0][-1][1]),'0')
        with self.assertRaisesRegex(ValueError,'legacy platform'):enum.enum_xml(xml(),'8.5.4.1878')

    def test_creation_graph(self):
        result=c.serialize(fixture());call=E.fromstring(result['request_xml'])
        new=next(v for v in result['descriptions'] if v['id']==const.CID)
        self.assertEqual(new['name'],'XML_Enum')
        self.assertEqual(new['class_id'],c.identifiers.class_id('Enum'))
        raw=s.inflate(base64.b64decode(result['data'])[18:]);_,pos=s.read_record(raw,0);storage,end=s.read_record(raw,pos+4)
        s.validate_storage(storage)
        meta,pos=s.read_record(storage,12);body,pos=s.read_record(storage,pos)
        doc=s.Parser(s.inflate(body).decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.val(doc[-1][1]),'2')
        self.assertEqual(len(call.find('{%s}params/{%s}features'%(s.NS,s.NS))),2)

if __name__=='__main__':unittest.main()
