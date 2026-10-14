"""Commit storage preserves manifest order and independently named streams."""
import base64,hashlib,sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import packet_builder as p
import metadata_serializer as s


class PacketBuilderTests(unittest.TestCase):
    def test_preserved_streams_validate_names_and_cached_versions(self):
        oid='11111111-1111-4111-8111-111111111111';version='22222222-2222-4222-8222-222222222222'
        m=[s.atom(0) for _ in range(17)];m[11]=[s.atom(1),s.atom(oid+'.0',True),s.atom(version)]
        docs=[m,[s.atom(0)],[s.atom(1),[s.atom(oid+'.0',True),s.atom(version),s.atom(1)]]]
        broken=copy.deepcopy(docs);broken[2][1][1]=s.atom(oid)
        with self.assertRaisesRegex(ValueError,'external context'):p.preserve_external_versions(broken,oid)
        broken=copy.deepcopy(docs);broken[0][11][1]=s.atom(version+'.0',True)
        with self.assertRaisesRegex(ValueError,'external object map'):p.preserve_external_versions(broken,oid)
        broken=copy.deepcopy(docs);broken[0][11][0]=s.atom(2)
        with self.assertRaisesRegex(ValueError,'external object map'):p.preserve_external_versions(broken,oid)

    def graph(self):return [[s.atom(0)] for _ in range(15)]

    def test_multiple_objects_and_streams_share_physical_records(self):
        body=s.compress(b'same body');first='11111111-1111-4111-8111-111111111111';second='22222222-2222-4222-8222-222222222222'
        entries=[p.ObjectRecord(second,b'meta2',body,((second+'.0',body),(second+'.1',b'other'))),p.ObjectRecord(first,b'meta1',body)]
        payload=p.assemble(self.graph(),entries)
        self.assertEqual(payload[:18],s.SERIALIZER)
        transport=s.inflate(payload[18:]);_,pos=s.read_record(transport,0)
        self.assertEqual(transport[pos:pos+4],bytes(4))
        storage,end=s.read_record(transport,pos+4);self.assertEqual(end,len(transport));s.validate_storage(storage)
        # Extract all physical records and find the manifest by its own SHA1.
        records={};pos=12
        import struct
        count=struct.unpack_from('<I',storage,8)[0]
        for _ in range(count):
            record,pos=s.read_record(storage,pos);records[hashlib.sha1(record).digest()]=record
        manifest=s.Parser(records[storage[-56:-36]].decode('utf-8-sig')).documents()[0]
        self.assertEqual([s.val(v) for v in manifest[:3]],['0','2',second])
        self.assertEqual(s.val(manifest[5]),'2')
        self.assertEqual(s.val(manifest[6]),second+'.0');self.assertEqual(s.val(manifest[8]),second+'.1')
        self.assertEqual(s.val(manifest[10]),first)
        self.assertEqual(s.val(manifest[4]),s.val(manifest[7]))
        self.assertEqual(count,5)  # Two metadata records, two payloads, manifest.

    def test_invalid_object_or_stream_sets(self):
        oid='11111111-1111-4111-8111-111111111111';obj=p.ObjectRecord(oid,b'meta',b'body')
        for entries in ([],[obj,obj],[p.ObjectRecord(oid,b'meta',b'body',(('x',b'a'),('x',b'b')))]):
            with self.subTest(entries=entries),self.assertRaises(ValueError):p.assemble(self.graph(),entries)
        with self.assertRaises(ValueError):p.assemble(self.graph()[:-1],[obj])


if __name__=='__main__':unittest.main()
