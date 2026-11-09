"""Large native envelopes: record limits and integrity remain independent."""
import hashlib
import os
from pathlib import Path
import struct
import sys
import unittest
import uuid
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import native_metadata as s
import packet_builder
import external_data


class LargePacketTests(unittest.TestCase):
    def test_native_commit_over_32_mib_and_256_objects_keeps_all_payloads(self):
        a=s.atom
        version='11111111-1111-4111-8111-111111111111'
        objects=[];expected={}
        for index in range(300):
            oid=str(uuid.UUID(int=index+1))
            raw=os.urandom(9*1024*1024) if index<4 else b'{0}'
            expected[oid]=hashlib.sha256(raw).digest()
            metadata=[a(5),a(oid),a(version),a(s.ZERO),a(s.ZERO),a(1),a(1),
                      a(version),a(version),a('Object'+str(index),True),a(index),
                      [a(0)],[a(0)],[a(0)],[a(0)],a('',True),a(0)]
            objects.append(packet_builder.ObjectRecord(oid,s.text_bytes([metadata,[a(0)],[a(0)]]),s.compress(raw)))
        packet=packet_builder.assemble([[a(0)] for _ in range(15)],objects)
        self.assertGreater(len(packet),32*1024*1024)
        self.assertEqual(packet[:len(s.SERIALIZER)],s.SERIALIZER)
        envelope=zlib.decompress(packet[len(s.SERIALIZER):],-15)
        graph,end=s.read_record(envelope,0)
        self.assertEqual(len(s.Parser(graph.decode('utf-8-sig')).documents()[0]),15)
        self.assertEqual(envelope[end:end+4],bytes(4))
        size=struct.unpack_from('<Q',envelope,end+4)[0]
        storage=envelope[end+12:]
        self.assertEqual(len(storage),size)
        s.validate_storage(storage)
        recovered=external_data.extract_many(storage)
        self.assertEqual(set(recovered),set(expected))
        import base64
        for oid,row in recovered.items():
            raw=s.inflate(base64.b64decode(row['data'],validate=True))
            self.assertEqual(hashlib.sha256(raw).digest(),expected[oid])


if __name__=='__main__':unittest.main()
