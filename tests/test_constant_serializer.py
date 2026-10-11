"""Synthetic protocol fixtures; no captured commits or credentials."""
import base64
import copy
import hashlib
import struct
import unittest
import uuid
import xml.etree.ElementTree as E
import test_comment_serializer as existing
import comment_serializer as s
import constant_serializer as c

CID='11111111-2222-4333-8444-555555555555'

def xml():
    return ('<MetaDataObject xmlns="%s" xmlns:v8="%s"><Constant uuid="%s"><Properties>'
            '<Name>XML_Constant</Name><Synonym><v8:item><v8:lang>ru</v8:lang>'
            '<v8:content>Тест &amp; кавычки "</v8:content></v8:item></Synonym>'
            '<Comment>Создано из XML</Comment><Type><v8:Type>xs:string</v8:Type>'
            '<v8:StringQualifiers><v8:Length>128</v8:Length><v8:AllowedLength>Variable</v8:AllowedLength>'
            '</v8:StringQualifiers></Type></Properties></Constant></MetaDataObject>')%(c.MD,c.CORE,CID)

def fixture():
    request,raw=existing.property_fixture()
    rootdocs=s.Parser(raw.decode('utf-8-sig')).documents()
    rootdocs[0].append([s.atom(c.CLASS),s.atom(0)])
    raw=s.text_bytes(rootdocs)
    oldmeta,_=s.read_record(base64.b64decode(request['snapshot']),12)
    rootmeta=s.Parser(oldmeta.decode('utf-8-sig')).documents()
    child=copy.deepcopy(rootmeta)
    child[0][1]=s.atom(existing.CHILD);child[0][2]=s.atom(c.LANGUAGE)
    child[0][3]=s.atom(existing.ID);child[0][9]=s.atom('Русский',True)
    child[0][12]=[s.atom(0)];child[0][13]=[s.atom(0)]
    child[0][14]=[s.atom(1),s.atom(existing.ID),s.atom(1)]
    child[0][15]=s.atom(c.LANGUAGE+'.Русский',True)
    def snapshot(meta,body):
        metadata=s.text_bytes(meta);data=s.compress(body)
        manifest=s.text_bytes([[s.atom(0),s.atom(1),meta[0][1],s.atom(hashlib.sha1(metadata).hexdigest(),True),s.atom(hashlib.sha1(data).hexdigest(),True),s.atom(0)]])
        return base64.b64encode(s.storage([metadata,data],manifest)).decode()
    request['snapshots']={existing.ID:snapshot(rootmeta,raw),existing.CHILD:snapshot(child,s.text_bytes([[s.atom('Language',True)]]))}
    request['context']=base64.b64encode(s.storage([s.text_bytes(rootmeta),s.text_bytes(child)],s.text_bytes([[s.atom(0)]]))).decode()
    request['constant_xml']=xml()
    return request

class ConstantSerializerTests(unittest.TestCase):
    def test_new_position_follows_collection_and_existing_positions_are_preserved(self):
        request=fixture()
        objects=c.context_objects(request['context'])
        rid=request['object_id'];root=objects[rid]
        old_ids=['aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb']
        root[0][12][0]=s.atom(2)
        root[0][12].append([s.atom(c.CLASS),s.atom(2)]+[s.atom(oid) for oid in old_ids])
        root[0][14]=[s.atom(3),s.atom(existing.CHILD)]+[s.atom(oid) for oid in old_ids]+[s.atom(0),s.atom(1),s.atom(1)]
        data=base64.b64decode(request['snapshots'][rid]);_,pos=s.read_record(data,12)
        content,_=s.read_record(data,pos);body=s.Parser(s.inflate(content).decode('utf-8-sig')).documents()
        # Context order deliberately differs from the native collection order.
        body[0][-1]=[s.atom(c.CLASS),s.atom(2)]+[s.atom(oid) for oid in reversed(old_ids)]
        def pack(metadata,raw):
            meta=s.text_bytes(metadata);compressed=s.compress(raw)
            manifest=s.text_bytes([[s.atom(0),s.atom(1),metadata[0][1],s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(compressed).hexdigest(),True),s.atom(0)]])
            return base64.b64encode(s.storage([meta,compressed],manifest)).decode()
        request['snapshots'][rid]=pack(root,s.text_bytes(body))
        for index,oid in enumerate(old_ids):
            obj=copy.deepcopy(objects[existing.CHILD]);obj[0][1]=s.atom(oid);obj[0][2]=s.atom(c.CLASS)
            obj[0][9]=s.atom('Old%d'%index,True);obj[0][10]=s.atom(0)
            objects[oid]=obj;request['snapshots'][oid]=pack(obj,s.text_bytes([[s.atom(1),s.atom(0)]]))
        request['context']=base64.b64encode(s.storage([s.text_bytes(obj) for obj in objects.values()],s.text_bytes([[s.atom(0)]]))).decode()
        result=c.serialize(request)
        expected={old_ids[1]:0,old_ids[0]:0,CID:2}
        descriptions={entry['id']:entry for entry in result['descriptions']}
        self.assertEqual({oid:descriptions[oid]['pos'] for oid in expected},expected)
        native=E.fromstring(result['request_xml'])
        for section in ('requested','changes'):
            for entry in native.findall('{%s}params/{%s}%s/{%s}value'%(s.NS,s.NS,section,s.NS)):
                oid=entry.find('{%s}first'%s.NS).get('value')
                if oid in expected:
                    self.assertEqual(int(entry.find('.//{%s}pos'%s.NS).get('value')),expected[oid])

    def test_create_graph_storage_and_xml(self):
        result=c.serialize(fixture())
        call=E.fromstring(result['request_xml']);p=call.find('{%s}params'%s.NS)
        self.assertIsNone(call.find('{%s}auth'%s.NS))
        self.assertEqual(result['object_id'],CID)
        self.assertEqual(len(result['descriptions']),3)
        blob=base64.b64decode(result['data']);raw=s.inflate(blob[18:])
        graph,pos=s.read_record(raw,0);snapshot,end=s.read_record(raw,pos+4)
        s.validate_storage(snapshot)
        self.assertEqual(struct.unpack_from('<I',snapshot,8)[0],7)
        docs=s.Parser(graph.decode('utf-8-sig')).documents()[0]
        # Graph relations are UUID/flag pairs, metadata relations are columns.
        self.assertEqual(s.render(docs[2][1]),'{%s,2,%s,0,%s,1}'%(existing.ID,existing.CHILD,CID))
        self.assertEqual(s.val(docs[6][2][0]),'1')
        self.assertEqual(s.val(docs[6][4][0]),'3')
        meta,pos=s.read_record(snapshot,12);data,pos=s.read_record(snapshot,pos)
        cm=s.Parser(meta.decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.val(cm[3]),existing.ID)
        self.assertEqual(s.val(cm[7]),s.val(cm[8]))
        body=s.Parser(s.inflate(data).decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.val(body[1][1][1][2][1][1]),'128')
        self.assertEqual(s.val(body[1][1][1][1][2]),'XML_Constant')
        self.assertEqual(len(p.find('{%s}changes'%s.NS)),3)

    def test_unsupported_properties_rejected(self):
        for mutation in ('<PasswordMode>true</PasswordMode>','<Unknown/>','<Name>Duplicate</Name>'):
            request=fixture();request['constant_xml']=xml().replace('</Properties>',mutation+'</Properties>')
            with self.assertRaises(ValueError):c.serialize(request)
        request=fixture();request['constant_xml']=xml().replace('xs:string','xs:decimal')
        with self.assertRaises(ValueError):c.serialize(request)

    def test_missing_snapshot_and_uuid_collision(self):
        request=fixture();request['snapshots'].pop(existing.CHILD)
        with self.assertRaises(ValueError):c.serialize(request)
        request=fixture();request['constant_xml']=xml().replace(CID,existing.CHILD)
        with self.assertRaises(ValueError):c.serialize(request)

    def test_snapshot_version_mismatch(self):
        request=fixture();data=base64.b64decode(request['context'])
        meta,pos=s.read_record(data,12);child,pos=s.read_record(data,pos)
        docs=s.Parser(meta.decode('utf-8-sig')).documents();docs[0][5]=s.atom(6)
        request['context']=base64.b64encode(s.storage([s.text_bytes(docs),child],s.text_bytes([[s.atom(0)]]))).decode()
        with self.assertRaisesRegex(ValueError,'mismatch'):c.serialize(request)

    def test_relation_order_is_semantic_but_flags_must_match(self):
        a=[s.atom(2),s.atom(existing.CHILD),s.atom(CID),s.atom(0),s.atom(1)]
        b=[s.atom(2),s.atom(CID),s.atom(existing.CHILD),s.atom(1),s.atom(0)]
        self.assertEqual(s.metadata_relations(a),s.metadata_relations(b))
        b[-1]=s.atom(1)
        self.assertNotEqual(s.metadata_relations(a),s.metadata_relations(b))
        b[2]=s.atom(CID)
        with self.assertRaises(ValueError):s.metadata_relations(b)

    def test_string_limits_and_invalid_xml(self):
        for before,after in [('128','0'),('128','1025'),('Variable','Fixed'),('XML_Constant','Bad name')]:
            with self.assertRaises(ValueError):c.constant_xml(xml().replace(before,after))
        with self.assertRaises(ValueError):c.constant_xml(xml().replace('xs:string','xs:decimal'))
        with self.assertRaisesRegex(ValueError,'DOCTYPE'):c.constant_xml('<!DOCTYPE MetaDataObject>'+xml())

    def test_generated_ids_are_unique_and_can_be_supplied(self):
        oid,name,body,ids=c.constant_xml(xml())
        self.assertEqual(len(set(ids)),6)
        blocks=[]
        for prefix,category in [('ConstantManager.','Manager'),('ConstantValueManager.','ValueManager'),('ConstantValueKey.','ValueKey')]:
            blocks.append('<xr:GeneratedType name="%sXML_Constant" category="%s"><xr:TypeId>%s</xr:TypeId><xr:ValueId>%s</xr:ValueId></xr:GeneratedType>'%(prefix,category,str(uuid.uuid4()),str(uuid.uuid4())))
        text=xml().replace('<Properties>','<InternalInfo xmlns:xr="%s">%s</InternalInfo><Properties>'%(c.READABLE,''.join(blocks)))
        _,_,_,supplied=c.constant_xml(text)
        self.assertEqual(len(set(supplied)),6)
        with self.assertRaises(ValueError):c.constant_xml(text.replace(supplied[1],supplied[0]))

    def test_storage_count_and_deduplication(self):
        data=s.storage([b'a',b'a',b'b'],b'manifest')
        self.assertEqual(struct.unpack_from('<I',data,8)[0],3)
        s.validate_storage(data)
        changed=bytearray(data);struct.pack_into('<I',changed,8,4)
        changed[-20:]=hashlib.sha1(changed[:-20]).digest()
        with self.assertRaises(ValueError):s.validate_storage(bytes(changed))

    def test_existing_serializer_relations_with_multiple_children(self):
        request,raw=existing.fixture()
        context=base64.b64decode(request['context']);meta,_=s.read_record(context,12)
        docs=s.Parser(meta.decode('utf-8-sig')).documents();docs[0][14]=[s.atom(2),s.atom(existing.CHILD),s.atom(CID),s.atom(0),s.atom(1)]
        request['context']=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode()
        text,_=s.serialize(request);p=E.fromstring(text).find('{%s}params'%s.NS)
        blob=base64.b64decode(p.find('{%s}data'%s.NS).text);graph,_=s.read_record(s.inflate(blob[18:]),0)
        self.assertEqual(s.render(s.Parser(graph.decode('utf-8-sig')).documents()[0][2][1]),'{%s,2,%s,0,%s,1}'%(existing.ID,existing.CHILD,CID))

if __name__=='__main__':unittest.main()
