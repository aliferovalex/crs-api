"""Inline attribute body, UUID feature map and source guards."""
import base64
import unittest
import uuid
from xml.etree import ElementTree as E
import test_catalog_form_serializer as catalog
import catalog_change_serializer as attributes
import metadata_serializer as s


def fixture():
    r=catalog.fixture();r.update(name='TestAttribute',length=100,repository='Synthetic',repository_version='22222222-2222-4222-8222-222222222222')
    return r


class AttributeTests(unittest.TestCase):
    def test_attribute_and_existing_properties(self):
        r=fixture();result=attributes.serialize(r);call=E.fromstring(result['request_xml'])
        data=base64.b64decode(call.find('{%s}params/{%s}data'%(s.NS,s.NS)).text)
        raw=s.inflate(data[18:]);graph,pos=s.read_record(raw,0);storage,end=s.read_record(raw,pos+4);s.validate_storage(storage)
        meta,pos=s.read_record(storage,12);body,pos=s.read_record(storage,pos)
        m=s.Parser(meta.decode('utf-8-sig')).documents()[0];doc=s.Parser(s.inflate(body).decode('utf-8-sig')).documents()[0]
        entry=doc[6][2];props=entry[0][1][1][1]
        self.assertEqual(s.val(props[1][2]),result['attribute_id']);self.assertEqual(s.val(props[2]),'TestAttribute')
        self.assertEqual(s.val(entry[0][1][1][2][1][1]),'100')
        self.assertEqual({s.val(v) for v in m[13][1:]},{result['attribute_id']})
        old=base64.b64decode(r['snapshot']);_,pos=s.read_record(old,12);oldbody,pos=s.read_record(old,pos)
        previous=s.Parser(s.inflate(oldbody).decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.render(previous[1]),s.render(doc[1]))
        self.assertEqual(s.val(doc[6][1]),'1')

    def test_second_attribute_and_duplicate_name(self):
        r=fixture();first=attributes.serialize(r);call=E.fromstring(first['request_xml'])
        data=base64.b64decode(call.find('{%s}params/{%s}data'%(s.NS,s.NS)).text)
        raw=s.inflate(data[18:]);_,pos=s.read_record(raw,0);storage,pos=s.read_record(raw,pos+4)
        meta,pos=s.read_record(storage,12);body,pos=s.read_record(storage,pos)
        docs=s.Parser(meta.decode('utf-8-sig')).documents();m=docs[0]
        m[0],m[5],m[6]=s.atom(5),s.atom(2),s.atom(2)
        for i in (7,8):m[i]=s.atom(str(uuid.UUID(bytes_le=base64.b64decode(s.val(m[i]))[:16])))
        from test_managed_form_serializer import store
        r.update(snapshot=store(docs,s.inflate(body)),context=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode())
        with self.assertRaisesRegex(ValueError,'already exists'):attributes.serialize(r)
        r['name']='SecondAttribute';result=attributes.serialize(r);self.assertNotEqual(first['attribute_id'],result['attribute_id'])
        call=E.fromstring(result['request_xml']);data=base64.b64decode(call.find('{%s}params/{%s}data'%(s.NS,s.NS)).text)
        raw=s.inflate(data[18:]);_,pos=s.read_record(raw,0);storage,pos=s.read_record(raw,pos+4)
        meta,pos=s.read_record(storage,12);body,pos=s.read_record(storage,pos)
        m=s.Parser(meta.decode('utf-8-sig')).documents()[0];doc=s.Parser(s.inflate(body).decode('utf-8-sig')).documents()[0]
        self.assertEqual({s.val(v) for v in m[13][1:]},{first['attribute_id'],result['attribute_id']})
        self.assertEqual([s.val(item[0][1][1][1][2]) for item in doc[6][2:]],['TestAttribute','SecondAttribute'])

    def test_invalid_name_length_version_and_platform(self):
        r=fixture()
        for key,value in [('name','bad name'),('length',0),('length',1025),('length',True),('length',1.5),('platform','8.5.4.1878'),('original_version','f'*40)]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):attributes.serialize(dict(r,**{key:value}))


if __name__=='__main__':unittest.main()
