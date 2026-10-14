"""Native managed form, owner collection and source version guards."""
import base64
import hashlib
import unittest
import uuid
import test_catalog_serializer as catalog
import test_constant_serializer as const
import managed_form_serializer as form
import metadata_serializer as s
import constant_serializer as c


def fixture():
    request=const.fixture('8.5.1.1529')
    raw=base64.b64decode(request['snapshots'][request['object_id']]);metadata,pos=s.read_record(raw,12)
    docs=s.Parser(metadata.decode('utf-8-sig')).documents();m=docs[0]
    m[1]=s.atom(const.CID);m[2]=s.atom(c.identifiers.class_id('Catalog'));m[3]=s.atom(request['object_id'])
    m[9]=s.atom('XML_Catalog',True);m[11]=m[12]=m[13]=[s.atom(0)]
    m[14]=[s.atom(1),m[3],s.atom(1)];m[15]=s.atom(c.identifiers.class_id('Catalog')+'.XML_Catalog',True)
    oid,name,body,ids=catalog.cat.object_xml(catalog.xml(), '8.5.1.1529', 'Catalog');data=s.compress(body);metadata=s.text_bytes(docs)
    manifest=s.text_bytes([[s.atom(0),s.atom(1),s.atom(oid),s.atom(hashlib.sha1(metadata).hexdigest(),True),s.atom(hashlib.sha1(data).hexdigest(),True),s.atom(0)]])
    return dict(platform='8.5.1.1529',object_id=oid,original_version=uuid.UUID(s.val(m[7])).bytes_le.hex()+'00000000',
        snapshot=base64.b64encode(s.storage([metadata,data],manifest)).decode(),
        context=base64.b64encode(s.storage([metadata],s.text_bytes([[s.atom(0)]]))).decode(),name='ФормаЭлемента')


def records(result):
    raw=s.inflate(base64.b64decode(result['data'])[18:]);graph,pos=s.read_record(raw,0);storage,end=s.read_record(raw,pos+4)
    s.validate_storage(storage);meta,pos=s.read_record(storage,12);body,pos=s.read_record(storage,pos);extra,pos=s.read_record(storage,pos)
    catalog_meta,pos=s.read_record(storage,pos);catalog_body,pos=s.read_record(storage,pos)
    return graph,s.Parser(meta.decode('utf-8-sig')).documents(),s.inflate(body),s.inflate(extra),s.Parser(catalog_meta.decode('utf-8-sig')).documents(),s.inflate(catalog_body)


class CatalogFormTests(unittest.TestCase):
    def test_form_parent_collection_and_attribute_type(self):
        r=fixture();result=form.serialize(r);graph,docs,body,extra,owner,owner_body=records(result)
        self.assertEqual(s.val(docs[0][2]),c.identifiers.class_id('CatalogForm'))
        self.assertEqual(s.val(docs[0][3]),const.CID)
        self.assertEqual(s.val(docs[0][9]),'ФормаЭлемента')
        self.assertEqual(s.val(owner[0][12][1][2]),result['object_id'])
        self.assertEqual(s.metadata_relations(owner[0][14]),{s.val(owner[0][3]):1})
        previous=base64.b64decode(r['snapshot']);_,pos=s.read_record(previous,12);data,pos=s.read_record(previous,pos)
        source=s.Parser(s.inflate(data).decode('utf-8-sig')).documents()[0]
        changed=s.Parser(owner_body.decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.render(source[1]),s.render(changed[1]))
        self.assertIn(s.val(source[1][1]),extra.decode('utf-8-sig'))
        self.assertNotIn('${catalog_object_type}',extra.decode('utf-8-sig'))
        self.assertIn('"Code"',extra.decode('utf-8-sig'))
        self.assertIn('"Description"',extra.decode('utf-8-sig'))
        self.assertEqual(result['externals'][0]['action'],0)

    def test_invalid_name_version_class_and_existing_children(self):
        r=fixture()
        for field,value in [('name','bad name'),('name','9Form'),('name','x'*81),('platform','8.5.4.1878'),('original_version','f'*40)]:
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):form.serialize(dict(r,**{field:value}))
        for field in (2,11,12):
            docs=s.context_metadata(base64.b64decode(r['context']),const.CID)
            docs[0][field]=s.atom(c.CLASS) if field==2 else [s.atom(1)]
            bad=dict(r,context=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode())
            with self.subTest(field=field),self.assertRaises(ValueError):form.serialize(bad)


if __name__=='__main__':unittest.main()
