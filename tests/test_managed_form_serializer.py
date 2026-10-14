"""Document/common form templates and existing sibling preservation."""
import base64
import hashlib
import unittest
import uuid
import test_catalog_form_serializer as catalog
import test_constant_serializer as const
import test_document_serializer as document
import managed_form_serializer as forms
import metadata_serializer as s
import constant_serializer as c


def store(docs, body):
    meta=s.text_bytes(docs);data=s.compress(body);oid=s.val(docs[0][1])
    manifest=s.text_bytes([[s.atom(0),s.atom(1),s.atom(oid),s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(data).hexdigest(),True),s.atom(0)]])
    return base64.b64encode(s.storage([meta,data],manifest)).decode()


class ManagedFormTests(unittest.TestCase):
    def test_historical_parent_relation_is_preserved_but_live_foreign_is_rejected(self):
        r=catalog.fixture();parent=s.context_metadata(base64.b64decode(r['context']),r['object_id'])
        historical='88888888-8888-4888-8888-888888888888';m=parent[0]
        m[14]=[s.atom(2),m[3],s.atom(historical),s.atom(1),s.atom(1)]
        data=base64.b64decode(r['snapshot']);_,pos=s.read_record(data,12);body,_=s.read_record(data,pos)
        r['snapshot']=store(parent,s.inflate(body))
        r['context']=base64.b64encode(s.storage([s.text_bytes(parent)],s.text_bytes([[s.atom(0)]]))).decode()
        result=forms.serialize(r);_,_,_,_,updated,_=catalog.records(result)
        self.assertEqual(s.metadata_relations(updated[0][14]),s.metadata_relations(m[14]))
        foreign=__import__('copy').deepcopy(parent);foreign[0][1]=s.atom(historical);foreign[0][3]=s.atom(s.ZERO)
        r['context']=base64.b64encode(s.storage([s.text_bytes(parent),s.text_bytes(foreign)],s.text_bytes([[s.atom(0)]]))).decode()
        with self.assertRaisesRegex(ValueError,'parent relations'):forms.serialize(r)

    def test_document_form(self):
        r=catalog.fixture();docs=s.context_metadata(base64.b64decode(r['context']),r['object_id'])
        docs[0][2]=s.atom(c.identifiers.class_id('Document'));docs[0][9]=s.atom('XML_Document',True)
        body=document.d.object_xml(document.xml(), '8.5.1.1529', 'Document')[2]
        r.update(form_kind='Document',snapshot=store(docs,body),context=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode())
        result=forms.serialize(r);_,new,body,external,parent,_=catalog.records(result)
        self.assertEqual(s.val(new[0][2]),c.identifiers.class_id('DocumentForm'))
        self.assertIn('"Number"',external.decode('utf-8-sig'));self.assertIn('"Date"',external.decode('utf-8-sig'))
        self.assertIn(s.val(s.Parser(body.decode('utf-8-sig')).documents()[0][1][1][1][1][2]),result['object_id'])

    def test_common_form_preserves_root_maps(self):
        r=const.fixture('8.5.1.1529');oid=r['object_id']
        snapshot=base64.b64decode(r['snapshots'][oid]);meta,pos=s.read_record(snapshot,12);data,pos=s.read_record(snapshot,pos)
        docs=s.Parser(meta.decode('utf-8-sig')).documents();body=s.Parser(s.inflate(data).decode('utf-8-sig')).documents()
        body[0].append([s.atom(c.identifiers.class_id('CommonForm')),s.atom(0)])
        request=dict(platform='8.5.1.1529',object_id=oid,original_version=uuid.UUID(s.val(docs[0][7])).bytes_le.hex()+'00000000',
            name='SharedForm',form_kind='CommonForm',context=r['context'],snapshot=store(docs,s.native_body_bytes(body)))
        previous=c.children(docs[0]);result=forms.serialize(request);_,new,_,external,parent,_=catalog.records(result)
        self.assertEqual(s.val(new[0][2]),c.identifiers.class_id('CommonForm'))
        self.assertTrue(set(previous).issubset(set(c.children(parent[0]))))
        self.assertIn(result['object_id'],s.metadata_relations(parent[0][14]))
        self.assertEqual(s.render(parent[0][13]),s.render(docs[0][13]))
        self.assertIn('"Message"',external.decode('utf-8-sig'))

    def test_second_form_preserves_first_and_rejects_duplicate_name(self):
        r=catalog.fixture();first=forms.serialize(r);_,child,_,_,parent,body=catalog.records(first)
        for docs in (parent,child):
            m=docs[0];m[0]=s.atom(5);m[5]=m[6]=s.atom(1)
            for i in (7,8):m[i]=s.atom(str(uuid.UUID(bytes_le=base64.b64decode(s.val(m[i]))[:16])))
        child[0][11][2]=s.atom(str(uuid.UUID(bytes_le=base64.b64decode(s.val(child[0][11][2]))[:16])))
        child[2]=[s.atom(0)]
        context=base64.b64encode(s.storage([s.text_bytes(parent),s.text_bytes(child)],s.text_bytes([[s.atom(0)]]))).decode()
        # A retrieval snapshot may omit child maps; updateInfo supplies them.
        parent[0][12]=[s.atom(0)]
        r.update(snapshot=store(parent,body),context=context)
        with self.assertRaisesRegex(ValueError,'already exists'):forms.serialize(r)
        r['name']='AnotherForm';second=forms.serialize(r);_,new,_,_,parent,_=catalog.records(second)
        self.assertEqual(s.val(new[0][10]),'1')
        self.assertEqual({v for v,cls in c.children(parent[0])},{first['object_id'],second['object_id']})
        # Native deletion retains surviving positions; the next free slot is
        # determined from metadata positions rather than collection length.
        context_docs=s.context_metadata(base64.b64decode(context),first['object_id']);context_docs[0][10]=s.atom(7)
        owner_docs=s.context_metadata(base64.b64decode(context),r['object_id'])
        r['context']=base64.b64encode(s.storage([s.text_bytes(owner_docs),s.text_bytes(context_docs)],s.text_bytes([[s.atom(0)]]))).decode()
        third=forms.serialize(r)
        self.assertEqual(next(item['pos'] for item in third['descriptions'] if item['id']==third['object_id']),8)


if __name__=='__main__':unittest.main()

