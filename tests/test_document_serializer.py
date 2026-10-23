"""Document body and creation graph checks using synthetic metadata."""
import base64
import hashlib
import unittest
import uuid
import xml.etree.ElementTree as E
import test_object_creation_serializer as const
import metadata_identifiers
import xml_namespaces
import object_creation_serializer as c
import native_metadata as s
import metadata_object_xml as d


def xml():
    return ('<MetaDataObject xmlns="%s" version="2.21"><Document uuid="%s">'
            '<Properties><Name>XML_Document</Name><Comment>Document test</Comment>'
            '</Properties><ChildObjects/></Document></MetaDataObject>')%(xml_namespaces.MD,const.CID)


def fixture():
    request=const.fixture('8.5.1.1529');rid=request['object_id']
    data=base64.b64decode(request['snapshots'][rid]);meta,pos=s.read_record(data,12);body,pos=s.read_record(data,pos)
    docs=s.Parser(s.inflate(body).decode('utf-8-sig')).documents()
    docs[0].append([s.atom(metadata_identifiers.class_id('Document')),s.atom(0)])
    body=s.compress(s.text_bytes(docs));m=s.Parser(meta.decode('utf-8-sig')).documents()[0]
    manifest=s.text_bytes([[s.atom(0),s.atom(1),m[1],s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(body).hexdigest(),True),s.atom(0)]])
    request['snapshots'][rid]=base64.b64encode(s.storage([meta,body],manifest)).decode()
    request.update(object_type='Document',object_xml=xml())
    return request


class DocumentSerializerTests(unittest.TestCase):
    def test_body_common_properties_and_generated_slots(self):
        oid,name,body,ids=d.object_xml(xml(), '8.5.1.1529', 'Document')
        n=s.Parser(body.decode('utf-8-sig')).documents()[0][1]
        self.assertEqual((oid,name),(const.CID,'XML_Document'))
        self.assertEqual([s.val(n[i]) for i in list(range(1,9))+[26,27]],ids)
        self.assertEqual(len(set(ids+[oid])),11)
        self.assertEqual(s.val(n[9][1][1][2]),oid)
        self.assertEqual(s.val(n[9][1][4]),'Document test')
        self.assertEqual((s.val(n[11]),s.val(n[12])),('1','9'))

    def test_explicit_generated_types_preserved(self):
        root=E.fromstring(xml());info=E.SubElement(root[0],'{%s}InternalInfo'%xml_namespaces.MD);ids=[]
        for category in ('Object','Ref','Selection','List','Manager'):
            node=E.SubElement(info,'{%s}GeneratedType'%xml_namespaces.READABLE,name='Document'+category+'.XML_Document',category=category)
            for key in ('TypeId','ValueId'):
                value=str(uuid.uuid4());ids.append(value);E.SubElement(node,'{%s}%s'%(xml_namespaces.READABLE,key)).text=value
        text=E.tostring(root,encoding='unicode')
        self.assertEqual(d.object_xml(text, '8.5.1.1529', 'Document')[3],ids)
        self.assertEqual(d.object_xml(text, '8.5.1.1529', 'Document')[2],d.object_xml(text, '8.5.1.1529', 'Document')[2])
        info[1][0].text=ids[0]
        with self.assertRaisesRegex(ValueError,'Duplicate generated'):d.object_xml(E.tostring(root,encoding='unicode'), '8.5.1.1529', 'Document')

    def test_rejects_nondefault_properties_children_and_wrong_class(self):
        for text in (xml().replace('</Properties>','<NumberLength>-1</NumberLength></Properties>'),
                     xml().replace('</Properties>','<Posting>Unknown</Posting></Properties>'),
                     xml().replace('</Properties>','<RegisterRecords><Record/></RegisterRecords></Properties>'),
                     xml().replace('<ChildObjects/>','<ChildObjects><Attribute/></ChildObjects>'),
                     xml().replace('Document uuid','Catalog uuid').replace('</Document>','</Catalog>'),
                     '<!DOCTYPE x>'+xml()):
            with self.subTest(text=text),self.assertRaises(ValueError):d.object_xml(text, '8.5.1.1529', 'Document')

    def test_document_graph_on_legacy_versions(self):
        for platform in ('8.5.1.1529','8.3.27.2342'):
            request=fixture();request['platform']=platform;result=c.serialize(request)
            call=E.fromstring(result['request_xml']);self.assertEqual(call.get('version'),platform)
            new=next(v for v in result['descriptions'] if v['id']==const.CID)
            self.assertEqual(new['class_id'],metadata_identifiers.class_id('Document'))
            features=call.find('{%s}params/{%s}features'%(s.NS,s.NS))
            self.assertEqual(len(features),2)
            self.assertTrue(all(len(entry.find('{%s}second'%s.NS))==0 for entry in features))
            raw=s.inflate(base64.b64decode(result['data'])[18:]);_,pos=s.read_record(raw,0);storage,end=s.read_record(raw,pos+4)
            s.validate_storage(storage)
        with self.assertRaisesRegex(ValueError,'legacy platform'):d.object_xml(xml(),'8.5.4.1878', 'Document')


if __name__=='__main__':unittest.main()
