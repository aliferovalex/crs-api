"""Incremental CF generations, selective streams and failed-update isolation."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import repository_cache as cache
import ibcmd_backend
import metadata_identifiers
import native_metadata as s
import external_data

ROOT='11111111-1111-4111-8111-111111111111'
CHILD='22222222-2222-4222-8222-222222222222'
REPO='33333333-3333-4333-8333-333333333333'
OLD='44444444-4444-4444-8444-444444444444'
NEW='55555555-5555-4555-8555-555555555555'
OTHER='66666666-6666-4666-8666-666666666666'


def docs(oid,parent,version=OLD,streams=None):
    a=s.atom;streams=streams or {}
    m=[a(5),a(oid),a(metadata_identifiers.class_id('Configuration' if parent==s.ZERO else 'Catalog')),
       a(parent),a(s.ZERO),a(1),a(1),a(version),a(version),a('Object',True),a(0),
       [a(len(streams))]+[v for name,version in streams.items() for v in (a(name,True),a(version))],
       [a(0)],[a(0)],[a(0)],a('descriptor',True),a(0)]
    return [m,[a(0)],[a(0)]]


def context(objects):return base64.b64encode(s.storage([s.text_bytes(row) for row in objects.values()],s.text_bytes([[s.atom(0)]]))).decode()


def snapshot(oid,description,body,streams=None):
    streams=streams or {};meta=s.text_bytes(description);body=s.compress(body)
    payloads=[meta,body];a=s.atom
    manifest=[a(0),a(1),a(oid),a(hashlib.sha1(meta).hexdigest(),True),a(hashlib.sha1(body).hexdigest(),True),a(len(streams))]
    for name,raw in streams.items():
        packed=s.compress(raw);payloads.append(packed);manifest.extend([a(name,True),a(hashlib.sha1(packed).hexdigest(),True)])
    return base64.b64encode(s.storage(payloads,s.text_bytes([manifest]))).decode()


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.work=Path(self.temp.name)
        self.cache=cache.Cache(self.work/'.crs-cache')
        self.objects={ROOT:docs(ROOT,s.ZERO),CHILD:docs(CHILD,ROOT,streams={CHILD+'.0':OLD,CHILD+'.1':OLD})}
        self.image={'root':s.text_bytes([[s.atom(2),s.atom(ROOT)]]),'version':b'{1,0}',ROOT:b'root body',CHILD:b'child body',CHILD+'.0':b'first',CHILD+'.1':b'second'}
        values={key:OLD for key in self.image};values.update(versions=OLD);values['']=OLD
        self.image['versions']=s.text_bytes([[s.atom(1),s.atom(len(values))]+[v for key,value in values.items() for v in (s.atom(key,True),s.atom(value))]])
        seed=self.work/'seed.cf';ibcmd_backend.write_cf(seed,self.image)
        self.request=dict(context=context(self.objects),repository_id=REPO,platform='8.5.1.1529',repository_version=OLD,seed_cf=str(seed))
        self.initial=self.cache.initialize(self.request)

    def update(self,objects=None,snapshots=None,**extra):
        request=dict(self.request,context=context(objects or self.objects),repository_version=NEW)
        plan=self.cache.plan(request)
        request.update(generation=plan['generation'],context_sha256=plan['context_sha256'],repository_version_after=NEW,snapshots=snapshots or {})
        request.update(extra)
        return self.cache.update(request)

    def bootstrap_request(self):
        source=self.cache.source(dict(self.request,snapshot_ids=[]))
        return dict(self.request,storage=source['storage'],repository_version_after=OLD)

    def test_bootstrap_without_seed_preserves_all_native_payloads(self):
        fresh=cache.Cache(self.work/'fresh')
        request=self.bootstrap_request();request.pop('seed_cf')
        fresh.bootstrap(request)
        state,image,_=fresh.load()
        for key in set(self.image)-cache.SERVICE:self.assertEqual(image[key],self.image[key])
        self.assertEqual(image['root'].decode('utf-8-sig'),'{2,'+ROOT+',}')
        version=s.Parser(image['version'].decode('utf-8-sig')).documents()
        self.assertEqual(s.val(version[0][0][0]),'216')
        self.assertEqual(state['objects'],self.cache.load()[0]['objects'])

    def test_bootstrap_rejects_stale_head_incomplete_data_and_unsupported_profile(self):
        request=self.bootstrap_request()
        for extra in [dict(repository_version_after=NEW),dict(platform='8.5.4.1878'),
                      dict(storage=snapshot(ROOT,self.objects[ROOT],b'root body'))]:
            fresh=cache.Cache(self.work/uuid.uuid4().hex)
            with self.subTest(extra=list(extra)),self.assertRaises(ValueError):fresh.bootstrap(dict(request,**extra))
            self.assertFalse((fresh.directory/'current.json').exists())

    def test_unchanged_cache_needs_no_snapshots_or_repacking(self):
        plan=self.cache.plan(self.request)
        self.assertEqual(plan['fetch'],[])
        request=dict(self.request,generation=plan['generation'],context_sha256=plan['context_sha256'],repository_version_after=OLD,snapshots={})
        with mock.patch.object(ibcmd_backend,'write_cf',side_effect=AssertionError('Unnecessary repacking')):
            result=self.cache.update(request)
        self.assertEqual(result['generation'],self.initial['generation'])

    def test_only_changed_body_is_fetched_and_other_records_are_identical(self):
        objects=copy.deepcopy(self.objects);objects[CHILD][0][7]=objects[CHILD][0][8]=s.atom(NEW)
        request=dict(self.request,context=context(objects));plan=self.cache.plan(request)
        self.assertEqual(plan['fetch'],[dict(object_id=CHILD,streams=[])])
        result=self.update(objects,{CHILD:snapshot(CHILD,objects[CHILD],b'new body')})
        state,image,_=self.cache.load()
        self.assertEqual(result['changed_body_ids'],[CHILD]);self.assertEqual(image[CHILD],b'new body')
        for key in self.image.keys()-{CHILD,'versions'}:self.assertEqual(image[key],self.image[key])
        self.assertEqual(state['repository_version'],NEW)

    def test_stream_only_update_requests_one_stream_and_preserves_other_stream(self):
        objects=copy.deepcopy(self.objects);objects[CHILD][0][11][2]=s.atom(NEW)
        plan=self.cache.plan(dict(self.request,context=context(objects)))
        self.assertEqual(plan['body_ids'],[])
        self.assertEqual([row['name'] for row in plan['fetch'][0]['streams']],[CHILD+'.0'])
        result=self.update(objects,{CHILD:snapshot(CHILD,objects[CHILD],self.image[CHILD],{CHILD+'.0':b'changed stream'})})
        _,image,_=self.cache.load()
        self.assertEqual(result['fetched_streams'],[CHILD+'.0']);self.assertEqual(image[CHILD+'.0'],b'changed stream')
        self.assertEqual(image[CHILD+'.1'],b'second');self.assertEqual(image[CHILD],self.image[CHILD])

    def test_new_and_deleted_entries_follow_the_complete_context(self):
        objects={ROOT:self.objects[ROOT],OTHER:docs(OTHER,ROOT,NEW)}
        plan=self.cache.plan(dict(self.request,context=context(objects)))
        self.assertEqual(plan['new_ids'],[OTHER]);self.assertEqual(plan['removed_ids'],[CHILD])
        result=self.update(objects,{OTHER:snapshot(OTHER,objects[OTHER],b'new object')})
        _,image,_=self.cache.load()
        self.assertEqual(image[OTHER],b'new object')
        self.assertFalse({CHILD,CHILD+'.0',CHILD+'.1'}&image.keys())
        self.assertEqual(set(cache.versions(image['versions'])),set(image)|{''})
        self.assertEqual(result['removed_ids'],[CHILD])

    def test_removed_stream_does_not_request_object_contents(self):
        objects=copy.deepcopy(self.objects);objects[CHILD][0][11]=[s.atom(1),s.atom(CHILD+'.0',True),s.atom(OLD)]
        self.assertEqual(self.cache.plan(dict(self.request,context=context(objects)))['fetch'],[])
        self.update(objects);self.assertNotIn(CHILD+'.1',self.cache.load()[1])

    def test_foreign_repository_platform_and_root_are_rejected(self):
        for extra in [dict(repository_id=OTHER),dict(platform='8.5.4.1878')]:
            with self.subTest(extra=extra),self.assertRaisesRegex(ValueError,'another repository'):
                self.cache.plan(dict(self.request,**extra))

    def test_racing_repository_or_cache_generation_cannot_publish(self):
        for extra in [dict(repository_version_after=OLD),dict(generation='f'*32),dict(context_sha256='wrong')]:
            with self.subTest(extra=extra),self.assertRaises(ValueError):self.update(**extra)
            self.assertEqual(self.cache.load()[0]['generation'],self.initial['generation'])

    def test_cache_file_tampering_is_detected(self):
        path=Path(self.initial['base_cf']);path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'CF checksum'):self.cache.load()

    def test_missing_snapshot_or_unrequested_stream_cannot_advance_cache(self):
        objects=copy.deepcopy(self.objects);objects[CHILD][0][8]=s.atom(NEW)
        with self.assertRaisesRegex(ValueError,'planned snapshots'):self.update(objects)
        with self.assertRaisesRegex(ValueError,'unrequested cache streams'):
            self.update(objects,{CHILD:snapshot(CHILD,objects[CHILD],b'new',{CHILD+'.0':b'unrequested'})})
        self.assertEqual(self.cache.load()[0]['generation'],self.initial['generation'])

    def test_changed_body_with_unchanged_version_is_rejected(self):
        objects=copy.deepcopy(self.objects);objects[CHILD][0][11][2]=s.atom(NEW)
        with self.assertRaisesRegex(ValueError,'without a changed repository version'):
            self.update(objects,{CHILD:snapshot(CHILD,objects[CHILD],b'wrong',{CHILD+'.0':b'changed'})})

    def test_partial_external_reader_is_opt_in_and_rejects_foreign_names(self):
        data=base64.b64decode(snapshot(CHILD,self.objects[CHILD],b'child body',{CHILD+'.0':b'first'}))
        with self.assertRaisesRegex(ValueError,'versions/manifest'):external_data.extract_many(data)
        self.assertEqual(len(external_data.extract_many(data,partial_externals=True)[CHILD]['externals']),1)
        data=base64.b64decode(snapshot(CHILD,self.objects[CHILD],b'child body',{OTHER+'.0':b'foreign'}))
        with self.assertRaisesRegex(ValueError,'versions/manifest'):external_data.extract_many(data,partial_externals=True)

    def test_feature_owned_streams_are_valid_but_foreign_and_ambiguous_owners_are_not(self):
        objects=copy.deepcopy(self.objects)
        objects[CHILD][0][13]=[s.atom(1),s.atom(OTHER)]
        refs=objects[CHILD][0][11];refs[0]=s.atom(3);refs.extend([s.atom(OTHER+'.2',True),s.atom(OLD)])
        _,records,_=cache.inventory(context(objects))
        self.assertIn(OTHER+'.2',records[CHILD]['externals'])
        objects[CHILD][0][13]=[s.atom(0)]
        with self.assertRaisesRegex(ValueError,'stream ownership'):cache.inventory(context(objects))
        objects[CHILD][0][13]=[s.atom(1),s.atom(ROOT)]
        with self.assertRaisesRegex(ValueError,'Ambiguous'):cache.inventory(context(objects))

    def test_complete_version_can_exceed_one_record_limit_and_still_validates_checksums(self):
        payload=s.storage([b'a'*(s.MAX_BYTES//2),b'b'*(s.MAX_BYTES//2)],s.text_bytes([[s.atom(0),s.atom(0)]]))
        self.assertGreater(len(payload),s.MAX_BYTES)
        s.validate_storage(payload)
        values,manifest=external_data.records(payload)
        self.assertEqual(len(values),3)
        self.assertEqual(s.render(manifest),'{0,0}')
        with mock.patch.object(external_data,'MAX_STORAGE_BYTES',len(payload)-1):
            with self.assertRaisesRegex(ValueError,'Unsupported version storage'):external_data.records(payload)
        damaged=bytearray(payload);damaged[20]^=1
        with self.assertRaisesRegex(ValueError,'checksum'):external_data.records(bytes(damaged))
        with self.assertRaisesRegex(ValueError,'checksum'):s.validate_storage(bytes(damaged))
        with mock.patch.object(s,'MAX_STORAGE_BYTES',len(payload)-1):
            with self.assertRaisesRegex(ValueError,'oversized'):s.validate_storage(payload)

    def test_large_cached_source_passes_the_same_decoder_as_preparation(self):
        import serialization_context
        image=dict(self.image)
        # Incompressible streams exceed even the old permissive base64 bound.
        image[CHILD+'.0']=os.urandom(12*1024*1024)
        image[CHILD+'.1']=os.urandom(12*1024*1024)
        state,_,cf=self.cache.load()
        with mock.patch.object(self.cache,'load',return_value=(state,image,cf)):
            result=self.cache.source(dict(self.request,snapshot_ids=[CHILD]))
        self.assertGreater(len(result['storage']),s.MAX_BYTES*2)
        data=serialization_context.decode(result['storage'],'Oversized version storage')
        s.validate_storage(data)
        records=external_data.extract_many(data,{CHILD})[CHILD]
        for row in records['externals']:
            self.assertEqual(s.inflate(base64.b64decode(row['data'])),image[row['name']])

    def test_interrupted_write_keeps_previous_generation_and_releases_lock(self):
        with mock.patch.object(ibcmd_backend,'write_cf',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):self.update()
        self.assertEqual(self.cache.load()[0]['generation'],self.initial['generation'])
        self.assertFalse((self.cache.directory/'write.lock').exists())

    def test_parallel_writer_cannot_enter_cache(self):
        with self.cache.locked():
            with self.assertRaisesRegex(ValueError,'already running'):self.update()

    def test_source_snapshots_and_full_storage_are_built_from_cached_records(self):
        request=dict(self.request,snapshot_ids=[CHILD])
        result=self.cache.source(request)
        self.assertEqual([row['object_id'] for row in result['snapshots']],[CHILD])
        selected=result['snapshots'][0]
        import serialization_context
        frame=serialization_context.read(dict(context=self.request['context'],snapshot=selected['snapshot']),CHILD)
        self.assertEqual(s.inflate(frame.data),self.image[CHILD])
        records=external_data.extract_many(base64.b64decode(result['storage']))
        self.assertEqual(set(records),set(self.objects))
        self.assertEqual({row['name'] for row in records[CHILD]['externals']},{CHILD+'.0',CHILD+'.1'})
        for row in records[CHILD]['externals']:
            self.assertEqual(s.inflate(base64.b64decode(row['data'])),self.image[row['name']])

    def test_source_cannot_use_stale_cache_or_invalid_snapshot_selection(self):
        for extra in [dict(repository_version=NEW,snapshot_ids=[CHILD]),dict(snapshot_ids=[OTHER]),dict(snapshot_ids=[CHILD,CHILD])]:
            with self.subTest(extra=extra),self.assertRaises(ValueError):self.cache.source(dict(self.request,**extra))

    def test_service_generation_changes_when_body_bytes_repeat_but_object_version_changes(self):
        objects=copy.deepcopy(self.objects);generations=[]
        for version in (NEW,OTHER):
            objects[CHILD][0][8]=s.atom(version)
            self.update(objects,{CHILD:snapshot(CHILD,objects[CHILD],self.image[CHILD])},
                        repository_version=version,repository_version_after=version)
            generations.append(cache.versions(self.cache.load()[1]['versions'])['versions'])
        self.assertNotEqual(*generations)


if __name__=='__main__':unittest.main()
