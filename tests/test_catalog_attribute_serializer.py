"""Inline attribute body, UUID feature map and source guards."""
import base64
import unittest
import uuid
from xml.etree import ElementTree as E
import test_catalog_form_serializer as catalog
import object_change_serializer as attributes
import inline_attribute_xml
import metadata_object_xml
import metadata_object_xml as xml
import json
from pathlib import Path
import native_metadata as s


AID='aaaaaaaa-1111-4111-8111-111111111111'


def fixture():
    r=catalog.fixture();r.pop('name');r.update(object_type='Catalog',repository='Synthetic',repository_version='22222222-2222-4222-8222-222222222222')
    snapshot=base64.b64decode(r['snapshot']);_,pos=s.read_record(snapshot,12);data,_=s.read_record(snapshot,pos)
    body=s.Parser(s.inflate(data).decode('utf-8-sig')).documents()[0]
    top=metadata_object_xml.export(body, {}, r['platform'], 'Catalog')
    template=json.loads(Path(s.__file__).with_name('catalog_attribute_layout_851.json').read_text(encoding='utf-8'))['template']
    entry=s.Parser(template).documents()[0];common=entry[0][1][1][1];common[1][2]=s.atom(AID);common[2]=s.atom('TestAttribute',True)
    entry[0][1][1][2][1][1]=s.atom(100)
    top[0].find(xml.Q + 'ChildObjects').append(inline_attribute_xml.attribute_export(entry))
    r['object_xml']=E.tostring(top,encoding='unicode')
    return r


class AttributeTests(unittest.TestCase):
    def test_attribute_and_existing_properties(self):
        r=fixture();result=attributes.serialize(r);call=E.fromstring(result['request_xml'])
        data=base64.b64decode(call.find('{%s}params/{%s}data'%(s.NS,s.NS)).text)
        raw=s.inflate(data[18:]);graph,pos=s.read_record(raw,0);storage,end=s.read_record(raw,pos+4);s.validate_storage(storage)
        meta,pos=s.read_record(storage,12);body,pos=s.read_record(storage,pos)
        m=s.Parser(meta.decode('utf-8-sig')).documents()[0];doc=s.Parser(s.inflate(body).decode('utf-8-sig')).documents()[0]
        entry=doc[6][2];props=entry[0][1][1][1]
        self.assertEqual(s.val(props[1][2]),AID);self.assertEqual(s.val(props[2]),'TestAttribute')
        self.assertEqual(s.val(entry[0][1][1][2][1][1]),'100')
        self.assertEqual({s.val(v) for v in m[13][1:]},{AID})
        old=base64.b64decode(r['snapshot']);_,pos=s.read_record(old,12);oldbody,pos=s.read_record(old,pos)
        previous=s.Parser(s.inflate(oldbody).decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.render(previous[1]),s.render(doc[1]))
        self.assertEqual(s.val(doc[6][1]),'1')

    def test_native_content_matches_single_object_packet(self):
        r=fixture();docs,native,payloads,externals=attributes.serialize(r,native_content=True)
        from test_whole_object_xml import body
        committed,contents=body(attributes.serialize(r))
        self.assertEqual(s.render(contents[0]),s.render(s.Parser(native.decode('utf-8-sig')).documents()[0]))
        for slot in (11,12,13,14):self.assertEqual(s.render(docs[0][slot]),s.render(committed[0][slot]))
        self.assertEqual(payloads,[]);self.assertEqual(externals,[])

    def test_second_attribute_and_duplicate_name(self):
        r=fixture();first=attributes.serialize(r);call=E.fromstring(first['request_xml'])
        data=base64.b64decode(call.find('{%s}params/{%s}data'%(s.NS,s.NS)).text)
        raw=s.inflate(data[18:]);_,pos=s.read_record(raw,0);storage,pos=s.read_record(raw,pos+4)
        meta,pos=s.read_record(storage,12);body,pos=s.read_record(storage,pos)
        docs=s.Parser(meta.decode('utf-8-sig')).documents();m=docs[0]
        m[0],m[5],m[6]=s.atom(5),s.atom(2),s.atom(2)
        for i in (7,8):m[i]=s.atom(str(uuid.UUID(bytes_le=base64.b64decode(s.val(m[i]))[:16])))
        from test_managed_form_creation import store
        r.update(snapshot=store(docs,s.inflate(body)),context=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode())
        top=E.fromstring(r['object_xml']);children=top[0].find(xml.Q+'ChildObjects')
        import copy
        node=copy.deepcopy(children[0]);node.set('uuid','bbbbbbbb-1111-4111-8111-111111111111');children.append(node)
        with self.assertRaisesRegex(ValueError,'Duplicate'):attributes.serialize(dict(r,object_xml=E.tostring(top,encoding='unicode')))
        node.find(xml.Q+'Properties/'+xml.Q+'Name').text='SecondAttribute'
        r['object_xml']=E.tostring(top,encoding='unicode');result=attributes.serialize(r)
        call=E.fromstring(result['request_xml']);data=base64.b64decode(call.find('{%s}params/{%s}data'%(s.NS,s.NS)).text)
        raw=s.inflate(data[18:]);_,pos=s.read_record(raw,0);storage,pos=s.read_record(raw,pos+4)
        meta,pos=s.read_record(storage,12);body,pos=s.read_record(storage,pos)
        m=s.Parser(meta.decode('utf-8-sig')).documents()[0];doc=s.Parser(s.inflate(body).decode('utf-8-sig')).documents()[0]
        self.assertEqual({s.val(v) for v in m[13][1:]},{AID,'bbbbbbbb-1111-4111-8111-111111111111'})
        self.assertEqual([s.val(item[0][1][1][1][2]) for item in doc[6][2:]],['TestAttribute','SecondAttribute'])

    def test_invalid_xml_version_and_platform(self):
        r=fixture()
        for key,value in [('object_xml','<invalid/>'),('platform','8.5.4.1878'),('original_version','f'*40)]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):attributes.serialize(dict(r,**{key:value}))
        old=dict(r);old.pop('object_xml');old.update(name='LegacyAttribute',length=100)
        with self.assertRaisesRegex(ValueError,'Complete object XML'):attributes.serialize(old)



if __name__=='__main__':unittest.main()
