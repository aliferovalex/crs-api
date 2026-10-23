"""Inline Enum values, generated UUIDs and creation graph regression checks."""
import base64,hashlib,json,unittest,xml.etree.ElementTree as E
from pathlib import Path
import test_object_creation_serializer as const
import metadata_identifiers
import xml_namespaces
import native_metadata as s
import object_creation_serializer as c
import metadata_object_xml as enum

V1='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
V2='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'

def xml():
    return ('<MetaDataObject xmlns="%s" version="2.21"><Enum uuid="%s">'
            '<Properties><Name>XML_Enum</Name><Comment>Enum test</Comment></Properties>'
            '<ChildObjects><EnumValue uuid="%s"><Properties><Name>First</Name><Color>auto</Color></Properties></EnumValue>'
            '<EnumValue uuid="%s"><Properties><Name>Second</Name></Properties></EnumValue></ChildObjects>'
            '</Enum></MetaDataObject>')%(xml_namespaces.MD,const.CID,V1,V2)

def fixture():
    request=const.fixture('8.5.1.1529');rid=request['object_id']
    data=base64.b64decode(request['snapshots'][rid]);meta,pos=s.read_record(data,12);body,pos=s.read_record(data,pos)
    docs=s.Parser(s.inflate(body).decode('utf-8-sig')).documents();docs[0].append([s.atom(metadata_identifiers.class_id('Enum')),s.atom(0)])
    body=s.compress(s.text_bytes(docs));m=s.Parser(meta.decode('utf-8-sig')).documents()[0]
    manifest=s.text_bytes([[s.atom(0),s.atom(1),m[1],s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(body).hexdigest(),True),s.atom(0)]])
    request['snapshots'][rid]=base64.b64encode(s.storage([meta,body],manifest)).decode()
    request.update(object_type='Enum',object_xml=xml());return request

class EnumSerializerTests(unittest.TestCase):
    def test_localized_properties_match_complete_native_objects(self):
        import v8unpack_backend as backend
        cases=json.loads(Path(__file__).with_name('fixtures').joinpath('enum_presentations_851.json').read_text(encoding='utf-8'))['cases']
        for case in cases:
            with self.subTest(case=case['name']):
                actual=enum.object_xml(case['xml'],'8.5.1.1529','Enum')[2]
                self.assertEqual(backend.signature(s.Parser(actual.decode('utf-8-sig')).documents()),backend.signature(s.Parser(case['body']).documents()))

    def test_localized_properties_reject_duplicate_languages_and_foreign_content(self):
        case=json.loads(Path(__file__).with_name('fixtures').joinpath('enum_presentations_851.json').read_text(encoding='utf-8'))['cases'][0]
        variants=[case['xml'].replace('<v8:lang>ru</v8:lang>','<v8:lang>en</v8:lang>'),case['xml'].replace('<ListPresentation>','<ListPresentation>ignored text'),case['xml'].replace('<v8:lang>en</v8:lang>','<v8:lang>en</v8:lang>ignored text')]
        for text in variants:
            with self.assertRaises(ValueError):enum.object_xml(text,'8.5.1.1529','Enum')

    def test_scalar_property_profiles_match_native_objects(self):
        import v8unpack_backend as backend
        cases=json.loads(Path(__file__).with_name('fixtures').joinpath('enum_properties_851.json').read_text(encoding='utf-8'))['cases']
        for case in cases:
            with self.subTest(case=case['name']):
                actual=enum.object_xml(case['xml'],'8.5.1.1529','Enum')[2]
                self.assertEqual(backend.signature(s.Parser(actual.decode('utf-8-sig')).documents()),backend.signature(s.Parser(case['body']).documents()))

    def test_scalar_property_invalid_values_are_rejected(self):
        for key,value in [('UseStandardCommands','1'),('QuickChoice','True'),('ChoiceMode','Unknown')]:
            text=xml().replace('<Name>XML_Enum</Name>','<Name>XML_Enum</Name><'+key+'>'+value+'</'+key+'>')
            with self.subTest(property=key),self.assertRaisesRegex(ValueError,'property value'):enum.object_xml(text,'8.5.1.1529','Enum')

    def test_complete_color_objects_match_independent_native_compilation(self):
        import v8unpack_backend as backend
        cases=json.loads(Path(__file__).with_name('fixtures').joinpath('enum_colors_851.json').read_text(encoding='utf-8'))['cases']
        for case in cases:
            with self.subTest(case=case['name']):
                actual=enum.object_xml(case['xml'],'8.5.1.1529','Enum')[2]
                self.assertEqual(backend.signature(s.Parser(actual.decode('utf-8-sig')).documents()),backend.signature(s.Parser(case['body']).documents()))

    def test_color_reference_uses_namespace_uri(self):
        import v8unpack_backend as backend
        case=json.loads(Path(__file__).with_name('fixtures').joinpath('enum_colors_851.json').read_text(encoding='utf-8'))['cases'][0]
        renamed=case['xml'].replace('xmlns:web=','xmlns:other=').replace('web:Red','other:Red')
        actual=enum.object_xml(renamed,'8.5.1.1529','Enum')[2]
        self.assertEqual(backend.signature(s.Parser(actual.decode('utf-8-sig')).documents()),backend.signature(s.Parser(case['body']).documents()))
        broken=renamed.replace('xmlns:other="http://v8.1c.ru/8.1/data/ui/colors/web"','xmlns:other="urn:unknown"')
        with self.assertRaisesRegex(ValueError,'color reference'):enum.object_xml(broken,'8.5.1.1529','Enum')

    def test_inline_values_and_object_name(self):
        oid,name,body,ids=enum.object_xml(xml(), '8.5.1.1529', 'Enum')
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
            with self.subTest(text=text),self.assertRaises(ValueError):enum.object_xml(text, '8.5.1.1529', 'Enum')

    def test_empty_values_and_legacy_profile(self):
        root=E.fromstring(xml());root[0].remove(root[0].find('{%s}ChildObjects'%xml_namespaces.MD))
        oid,name,body,ids=enum.object_xml(E.tostring(root,encoding='unicode'),'8.3.27.2342', 'Enum')
        self.assertEqual(len(ids),6)
        self.assertEqual(s.val(s.Parser(body.decode('utf-8-sig')).documents()[0][-1][1]),'0')
        with self.assertRaisesRegex(ValueError,'legacy platform'):enum.object_xml(xml(),'8.5.4.1878', 'Enum')

    def test_creation_graph(self):
        result=c.serialize(fixture());call=E.fromstring(result['request_xml'])
        new=next(v for v in result['descriptions'] if v['id']==const.CID)
        self.assertEqual(new['name'],'XML_Enum')
        self.assertEqual(new['class_id'],metadata_identifiers.class_id('Enum'))
        raw=s.inflate(base64.b64decode(result['data'])[18:]);_,pos=s.read_record(raw,0);storage,end=s.read_record(raw,pos+4)
        s.validate_storage(storage)
        meta,pos=s.read_record(storage,12);body,pos=s.read_record(storage,pos)
        doc=s.Parser(s.inflate(body).decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.val(doc[-1][1]),'2')
        self.assertEqual(len(call.find('{%s}params/{%s}features'%(s.NS,s.NS))),2)

if __name__=='__main__':unittest.main()
