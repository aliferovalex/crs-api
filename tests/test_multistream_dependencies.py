"""Structured links and opaque companions share one owned-stream classifier."""
import base64
import copy
import json
from pathlib import Path
import struct
import sys
import types
import unittest
import uuid
from unittest import mock
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_dependencies
import compiled_metadata
import external_dependencies as dependencies
import metadata_identifiers as identifiers
import native_metadata as s
import native_streams
import native_content
from test_repository_cache import docs as cache_docs

TARGET='22222222-2222-4222-8222-222222222222'
PARENT='33333333-3333-4333-8333-333333333333'
VERSION='44444444-4444-4444-8444-444444444444'


class MultistreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved=json.loads((Path(__file__).parent/'fixtures/native_multistream_form.json').read_text(encoding='utf-8'))
        cls.fixture=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))

    def form(self):
        return self.fixture['object_id'],{name:base64.b64decode(raw) for name,raw in self.fixture['streams'].items()}

    def test_real_form_interface_module_bundle_and_help_have_distinct_roles(self):
        oid,streams=self.form()
        self.assertEqual(native_streams.roles(self.fixture['kind'],oid,streams),
                         {oid+'.0':'managed-form',oid+'.1':'help'})
        expected=dependencies.stream_ids(self.fixture['kind'],base64.b64decode(self.fixture['body']),streams[oid+'.0'])
        self.assertTrue(expected)
        self.assertEqual(dependencies.stream_references(self.fixture['kind'],oid,
            base64.b64decode(self.fixture['body']),streams),expected)

    def test_help_modules_and_unclassified_bytes_are_not_scanned_for_uuid_text(self):
        oid,streams=self.form();body=base64.b64decode(self.fixture['body'])
        expected=dependencies.stream_references(self.fixture['kind'],oid,body,streams)
        streams[oid+'.1']=TARGET.encode();streams[oid+'.custom']=b'\xff'+TARGET.encode()
        self.assertEqual(dependencies.stream_references(self.fixture['kind'],oid,body,streams),expected)
        self.assertEqual(native_streams.roles('Catalog',oid,[oid+'.0',oid+'.3',oid+'.1',oid+'.custom']),
                         {oid+'.0':'module',oid+'.1':'help',oid+'.3':'module',oid+'.custom':'opaque'})

    def test_foreign_stream_and_missing_form_interface_are_rejected(self):
        oid,_=self.form()
        with self.assertRaisesRegex(ValueError,'another object'):
            native_streams.roles('CatalogForm',oid,[TARGET+'.0'])
        with self.assertRaisesRegex(ValueError,'Missing managed form interface'):
            dependencies.stream_references('CatalogForm',oid,b'body',{oid+'.1':b'help'})

    def test_additional_role_streams_do_not_disable_rights_checks(self):
        oid,_=self.form()
        rights=('{10,{1,{{1,'+TARGET+',0,0},{0}}},0,0,0,0,0}').encode()
        self.assertEqual(dependencies.stream_references('Role',oid,b'body',
            {oid+'.0':rights,oid+'.extra':b'opaque'}),{TARGET})
        with self.assertRaisesRegex(ValueError,'role file'):
            dependencies.stream_references('Role',oid,b'body',{oid+'.0':b'corrupted',oid+'.extra':b'opaque'})

    def test_compiled_role_graph_keeps_right_dependencies_with_extra_streams(self):
        oid,_=self.form();body=s.native_body_bytes([[s.atom(0),[s.atom(3),[s.atom(1),s.atom(0),s.atom(oid)],s.atom('Role',True)]]])
        record=dict(id=oid,kind='Role')
        facts=types.SimpleNamespace(features=(),generated=(),children={},parent_id=PARENT)
        index=types.SimpleNamespace(inventory={oid:record,TARGET:dict(kind='Catalog')},facts=lambda _:facts,
            owner_for_generated=lambda _:None,feature_owners={},resolve_required=lambda _: {},object_ids_required=lambda _:set())
        rights=('{10,{1,{{1,'+TARGET+',0,0},{0}}},0,0,0,0,0}').encode()
        result=compiled_dependencies.references(index,record,body,
            {oid:body,oid+'.0':rights,oid+'.extra':b'opaque'},'<Role/>')
        self.assertEqual(result,{TARGET:0,PARENT:1})

    def test_schema_keeps_type_checks_with_other_template_streams(self):
        oid,_=self.form();main=('<Schema xmlns:c="http://v8.1c.ru/8.1/data/core"><c:TypeId>'+TARGET+'</c:TypeId></Schema>').encode()
        layout=b'<Layout/>';schema=struct.pack('<IIQ',0,0,len(main))+main+layout
        body=b'{0,{0,6,0},0}'
        self.assertEqual(dependencies.stream_references('Template',oid,body,
            {oid+'.0':schema,oid+'.extra':b'opaque'}),{TARGET})
        with self.assertRaisesRegex(ValueError,'schema'):
            dependencies.stream_references('Template',oid,body,{oid+'.0':b'bad',oid+'.extra':b'opaque'})

    def test_text_binary_and_spreadsheet_template_payloads_remain_opaque(self):
        oid,_=self.form()
        for code in (0,1,4,8):
            with self.subTest(code=code):
                self.assertEqual(dependencies.stream_references('Template',oid,('{0,{0,'+str(code)+',0},0}').encode(),
                    {oid+'.0':TARGET.encode(),oid+'.extra':b'\xff'}),set())

    def frame(self,oid,kind):
        a=s.atom
        m=[a(5),a(oid),a(identifiers.class_id(kind)),a(PARENT),a(s.ZERO),a(1),a(0),a(VERSION),a(VERSION),
           a('Form',True),a(0),[a(2),a(oid+'.0',True),a(VERSION),a(oid+'.1',True),a(VERSION)],
           [a(0)],[a(0)],[a(1),a(PARENT),a(1)],a('',True),a(0)]
        docs=[m,[a(0)],[a(0)]]
        return types.SimpleNamespace(metadata=m,docs=docs,saved=copy.deepcopy(docs))

    def change_form(self,after):
        oid,before=self.form();body=base64.b64decode(self.fixture['body']);kind=self.fixture['kind'];frame=self.frame(oid,kind)
        request=dict(platform='8.5.1.1529',snapshots={oid:'snapshot'},originals={oid:uuid.UUID(VERSION).bytes_le.hex()+'00000000'},storage='storage')
        images=dict(before,**{oid:body,PARENT:b'{0}'})
        result=dict(after,**{oid:body,PARENT:b'{0}'})
        with mock.patch.object(compiled_metadata.serialization_context,'read',return_value=frame), \
             mock.patch.object(compiled_metadata.serialization_context,'decode',return_value=b'storage'), \
             mock.patch.object(compiled_metadata,'validate_form_interface') as verify, \
             mock.patch.object(compiled_metadata.metadata_references,'form_relations',return_value=frame.metadata[14]):
            entry=compiled_metadata.content(request,dict(object_id=oid,kind=kind,form_xml='<Form/>'),
                {oid:frame.docs,PARENT:frame.docs},images,result)
        verify.assert_called_once()
        return entry

    def test_embedded_command_stream_is_changed_or_removed_with_its_owner(self):
        metadata=cache_docs(PARENT,s.ZERO,streams={TARGET+'.2':VERSION})
        metadata[0][13]=[s.atom(1),s.atom(TARGET)]
        before={TARGET+'.2':b'old module'};after={TARGET+'.2':b'new module'}
        entry=native_content.compiled_stream_changes(copy.deepcopy(metadata),metadata,b'body',PARENT,before,after,{TARGET+'.2'})
        self.assertEqual([(name,s.inflate(raw)) for name,raw in entry.streams],[(TARGET+'.2',b'new module')])
        self.assertEqual(entry.externals[0]['action'],1)
        changed=copy.deepcopy(metadata);changed[0][13]=[s.atom(0)]
        entry=native_content.compiled_stream_changes(changed,metadata,b'body',PARENT,before,{},{TARGET+'.2'})
        self.assertEqual(entry.externals,[])
        with self.assertRaisesRegex(ValueError,'ownership'):
            native_content.compiled_stream_changes(copy.deepcopy(metadata),metadata,b'body',PARENT,{},
                {VERSION+'.2':b'foreign'},{VERSION+'.2'})

    def test_help_only_edit_preserves_interface_version_and_sends_only_help(self):
        oid,before=self.form();after=dict(before);after[oid+'.1']=b'new compiled help'
        result=self.change_form(after);rows={row['name']:row for row in result.externals}
        self.assertEqual([(name,s.inflate(raw)) for name,raw in result.streams],[(oid+'.1',after[oid+'.1'])])
        self.assertEqual(rows[oid+'.0']['action'],0)
        self.assertEqual(rows[oid+'.0']['version'],(uuid.UUID(VERSION).bytes_le+bytes(4)).hex())
        self.assertEqual(rows[oid+'.1']['action'],1)

    def test_removing_help_preserves_the_interface(self):
        oid,before=self.form();before.pop(oid+'.1');result=self.change_form(before)
        self.assertEqual(result.streams,[])
        self.assertEqual([row['name'] for row in result.externals],[oid+'.0'])

    def test_new_opaque_companion_is_packed_without_resending_other_streams(self):
        oid,before=self.form();after=dict(before);after[oid+'.extra']=b'new opaque companion'
        result=self.change_form(after)
        self.assertEqual([(name,s.inflate(raw)) for name,raw in result.streams],[(oid+'.extra',after[oid+'.extra'])])
        self.assertEqual({row['name']:row['action'] for row in result.externals},
                         {oid+'.0':0,oid+'.1':0,oid+'.extra':1})


if __name__=='__main__':unittest.main()
