"""Synthetic Catalog XML and cross-object graph regression checks."""
import base64
import unittest
import uuid
import xml.etree.ElementTree as E
import test_constant_serializer as const
import catalog_serializer as cat
import constant_serializer as c
import metadata_serializer as s


def xml():
    return ('<MetaDataObject xmlns="%s" version="2.21"><Catalog uuid="%s">'
            '<Properties><Name>XML_Catalog</Name><Comment>Catalog test</Comment>'
            '</Properties><ChildObjects/></Catalog></MetaDataObject>')%(c.MD,const.CID)


class CatalogSerializerTests(unittest.TestCase):
    def test_generated_types_and_common_properties(self):
        oid,name,body,ids=cat.catalog_xml(xml())
        n=s.Parser(body.decode('utf-8-sig')).documents()[0][1]
        self.assertEqual((oid,name),(const.CID,'XML_Catalog'))
        self.assertEqual([s.val(n[i]) for i in list(range(1,9))+[34,35]],ids)
        self.assertEqual(len(set(ids+[oid])),11)
        self.assertEqual(s.val(n[9][1][1][2]),oid)
        self.assertEqual(s.val(n[9][1][4]),'Catalog test')
        self.assertEqual((s.val(n[17]),s.val(n[19])),('9','25'))

    def test_explicit_generated_types_round_trip(self):
        root=E.fromstring(xml());obj=root[0];info=E.SubElement(obj,'{%s}InternalInfo'%c.MD)
        ids=[]
        for category in ('Object','Ref','Selection','List','Manager'):
            node=E.SubElement(info,'{%s}GeneratedType'%c.READABLE,name='Catalog'+category+'.XML_Catalog',category=category)
            for key in ('TypeId','ValueId'):
                value=str(uuid.uuid4());ids.append(value);E.SubElement(node,'{%s}%s'%(c.READABLE,key)).text=value
        text=E.tostring(root,encoding='unicode')
        self.assertEqual(cat.catalog_xml(text)[3],ids)
        self.assertEqual(cat.catalog_xml(text)[2],cat.catalog_xml(text)[2])
        info[1][0].text=ids[0]
        with self.assertRaisesRegex(ValueError,'Duplicate generated'):
            cat.catalog_xml(E.tostring(root,encoding='unicode'))

    def test_unsupported_children_properties_and_platform(self):
        cases=[xml().replace('<ChildObjects/>','<ChildObjects><Attribute/></ChildObjects>'),
               xml().replace('</Properties>','<Hierarchical>true</Hierarchical></Properties>'),
               xml().replace('</Properties>','<Name>Duplicate</Name></Properties>'),
               '<!DOCTYPE x>'+xml()]
        for text in cases:
            with self.subTest(text=text),self.assertRaises(ValueError):cat.catalog_xml(text)
        with self.assertRaisesRegex(ValueError,'platform'):cat.catalog_xml(xml(),'8.5.4.1878')

    def test_catalog_creation_graph_and_empty_features(self):
        request=const.fixture('8.5.1.1529')
        # Add an empty Catalog collection to the synthetic root body.
        rid=request['object_id'];data=base64.b64decode(request['snapshots'][rid])
        meta,pos=s.read_record(data,12);compressed,pos=s.read_record(data,pos)
        docs=s.Parser(s.inflate(compressed).decode('utf-8-sig')).documents()
        docs[0].append([s.atom(c.identifiers.class_id('Catalog')),s.atom(0)])
        import hashlib
        body=s.compress(s.text_bytes(docs))
        m=s.Parser(meta.decode('utf-8-sig')).documents()[0]
        manifest=s.text_bytes([[s.atom(0),s.atom(1),m[1],s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(body).hexdigest(),True),s.atom(0)]])
        request['snapshots'][rid]=base64.b64encode(s.storage([meta,body],manifest)).decode()
        request.update(object_type='Catalog',catalog_xml=xml())
        result=c.serialize(request)
        new=next(v for v in result['descriptions'] if v['id']==const.CID)
        self.assertEqual(new['class_id'],c.identifiers.class_id('Catalog'))
        p=E.fromstring(result['request_xml']).find('{%s}params'%s.NS)
        features=p.find('{%s}features'%s.NS)
        self.assertEqual(len(features),2)
        self.assertTrue(all(len(entry.find('{%s}second'%s.NS))==0 for entry in features))
        raw=s.inflate(base64.b64decode(result['data'])[18:]);_,pos=s.read_record(raw,0);storage,end=s.read_record(raw,pos+4)
        s.validate_storage(storage)


if __name__=='__main__':unittest.main()
