"""Commit history uses the actual root Version, including an intentional empty value."""
import base64
import copy
import os
from pathlib import Path
import sys
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import configuration_version as version
import native_metadata as s
import packet_builder
from test_configuration_root import OID,OTHER,body,frame
from test_repository_cache import snapshot


def root_body(code):return s.text_bytes(body(version=code))


def root_packet(code):
    context,_=frame();docs=copy.deepcopy(context.docs);docs[0][0]=s.atom(6)
    return packet_builder.assemble([[s.atom(0)] for _ in range(15)],
                                  [packet_builder.ObjectRecord(OID,s.text_bytes(docs),s.compress(root_body(code)))])


class ConfigurationVersionTests(unittest.TestCase):
    def request(self,code='',mode='snapshot'):
        context,_=frame()
        data=snapshot(OID,context.docs,root_body(code)) if mode=='snapshot' else base64.b64encode(root_packet(code)).decode()
        value=uuid.UUID(OTHER).bytes_le.hex()+'00000000'
        return dict(mode=mode,object_id=OID,data=data,platform='8.5.1.1529',original=value,local=value)

    def test_current_root_and_changed_root_both_supply_exact_version(self):
        for mode in ('snapshot','packet'):
            for code in ('2.5.22.149/3.2.45.12','','2.0 & "тест"'):
                for platform in ('8.3.27.1936','8.5.1.1529'):
                    with self.subTest(mode=mode,code=code,platform=platform):
                        self.assertEqual(version.read(dict(self.request(code,mode),platform=platform))['version_code'],code)

    def test_foreign_or_corrupt_source_is_rejected(self):
        for field,value in [('object_id',OTHER),('local','f'*40),('original','f'*40),('data','invalid')]:
            with self.subTest(field=field),self.assertRaises((ValueError,KeyError)):
                version.read(dict(self.request(),**{field:value}))
        for mode in ('snapshot','packet'):
            request=self.request('1.0',mode);request['data']=request['data'][:-5]
            with self.assertRaises(ValueError):version.read(request)

    def test_outer_storage_uses_storage_budget_not_single_record_budget(self):
        context,_=frame();docs=context.docs;docs[0][0]=s.atom(6)
        blob=s.compress(os.urandom(1024*1024))
        packet=packet_builder.assemble([[s.atom(0)] for _ in range(15)],
            [packet_builder.ObjectRecord(OID,s.text_bytes(docs),s.compress(root_body('large')),
                tuple((OID+'.'+str(i),blob) for i in range(17)))])
        request=self.request(mode='packet');request['data']=base64.b64encode(packet).decode()
        self.assertEqual(version.read(request)['version_code'],'large')

    def test_retained_8327_root_uses_verified_prefix_and_leaves_tail_opaque(self):
        documents=body(version='2.5.22.149/3.2.45.12');props=documents[0][3][1][1]
        props[:]=props[:61];props[0]=s.atom(68)
        documents[0][3][1].append([s.atom(0)])
        self.assertEqual(version.from_body(s.text_bytes(documents),OID,'8.3.27.1936'),'2.5.22.149/3.2.45.12')
        props[15]=s.atom(123)
        with self.assertRaisesRegex(ValueError,'not a string'):version.from_body(s.text_bytes(documents),OID,'8.3.27.1936')


if __name__=='__main__':unittest.main()
