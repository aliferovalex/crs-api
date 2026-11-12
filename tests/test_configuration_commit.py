"""ibcmd-only preparation, source guards and one final repository package."""
import base64,types,uuid
import copy
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'Сериализация'))
import configuration_commit as commit
import compiled_metadata
import ibcmd_backend
import metadata_context
import native_metadata as s
import serialization_context
import compiled_image,native_content,metadata_identifiers


class ConfigurationCommitTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Path(__file__).with_name('fixtures') / 'ibcmd_document'
        self.case = json.loads((self.fixture / 'request.json').read_text(encoding='utf-8'))
        self.request = copy.deepcopy(self.case['request'])
        for key in ('directory', 'baseline_directory'):
            self.request[key] = str(self.fixture / self.request[key])
        for oid,docs in metadata_context.context_objects(self.request['context']).items():
            if oid not in self.request['snapshots']:
                self.request['snapshots'][oid]=base64.b64encode(s.storage([s.text_bytes(docs),s.compress(s.native_body_bytes([[s.atom(oid)]]))],s.text_bytes([[s.atom(0)]]))).decode()
                self.request['originals'][oid]=uuid.UUID(s.val(docs[0][7])).bytes_le.hex()+'00000000'
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        placeholder = Path(self.temp.name) / 'compiler'
        placeholder.write_bytes(b'placeholder')
        self.request['compiler'] = dict(backend='ibcmd', executable=str(placeholder), base_cf=str(placeholder))

    def prepared(self, compiler, request, plan, changes, objects):
        compiler.object_ids = {row['object_id'] for row in changes}
        compiler.before = {key: value.encode('utf-8') for key, value in self.case['before'].items()}
        compiler.after = {key: value.encode('utf-8') for key, value in self.case['after'].items()}
        compiler.delta=compiled_image.Delta(compiler.before,compiler.after,compiler.before,compiler.after,{})
        target = commit.export.inventory(request['directory'])[2]
        for row in changes:
            compiled_metadata.validate_xml(row, Path(request['baseline_directory']),
                                          Path(request['directory']), Path(target[row['object_id']]['path']))

    def test_no_default_compiler_or_fallback(self):
        self.request.pop('compiler')
        with self.assertRaisesRegex(ValueError, 'Compiler requires'):
            commit.serialize(self.request)

    def test_history_version_comes_from_verified_target_root(self):
        request=copy.deepcopy(self.request)
        for key in ('directory','baseline_directory'):
            folder=Path(self.temp.name)/key;shutil.copytree(request[key],folder);request[key]=str(folder)
            root=folder/'Configuration.xml';raw=root.read_bytes()
            self.assertIn(b'<Version/>',raw)
            root.write_bytes(raw.replace(b'<Version/>',b'<Version>2.6 &amp; new</Version>'))
        plan=commit.export.plan(request)
        for key in ('target_fingerprint','baseline_fingerprint'):request[key]=plan[key]
        with mock.patch.object(ibcmd_backend.Compiler,'prepare',autospec=True,side_effect=self.prepared):
            result=commit.serialize(request)
        self.assertEqual(result['version_code'],'2.6 & new')
        self.assertTrue(result['version_code_resolved'])

    def test_compiler_error_propagates_without_building_a_packet(self):
        with mock.patch.object(ibcmd_backend.Compiler, 'prepare', side_effect=ValueError('upstream rejected type')), \
                mock.patch.object(commit.packets, 'assemble') as assemble:
            with self.assertRaisesRegex(ValueError, 'upstream rejected type'):
                commit.serialize(self.request)
            assemble.assert_not_called()

    def test_native_content_from_compiler_is_packed_once(self):
        with mock.patch.object(ibcmd_backend.Compiler, 'prepare', autospec=True, side_effect=self.prepared), \
                mock.patch.object(commit.packets, 'assemble', wraps=commit.packets.assemble) as assemble:
            result = commit.serialize(self.request)
        self.assertEqual(assemble.call_count, 1)
        records = assemble.call_args.args[1]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(s.inflate(record.body), self.case['after'][record.object_id].encode('utf-8'))
        self.assertEqual(result['changed_ids'], [record.object_id])
        self.assertEqual(result['new_ids'], [])
        self.assertEqual(result['removed_ids'], [])
        self.assertEqual(len(result['requested']), len(metadata_context.context_objects(self.request['context'])))

    def test_changed_directory_fingerprint_rejected_before_compilation(self):
        self.request['target_fingerprint'] = 'changed'
        with mock.patch.object(ibcmd_backend.Compiler, 'prepare') as prepare:
            with self.assertRaisesRegex(ValueError, 'directories changed'):
                commit.serialize(self.request)
            prepare.assert_not_called()

    def test_rename_keeps_uuid_and_updates_committed_name_and_descriptor(self):
        target=Path(self.temp.name)/'renamed';shutil.copytree(self.request['directory'],target)
        old='CRSAPI_TestDocument';new='RenamedDocument'
        for path in target.rglob('*.xml'):
            if path.name=='ConfigDumpInfo.xml':continue
            path.write_text(path.read_text(encoding='utf-8-sig').replace(old,new),encoding='utf-8')
        (target/'Documents'/(old+'.xml')).rename(target/'Documents'/(new+'.xml'))
        self.request['directory']=str(target)
        self.request['target_fingerprint']=commit.export.plan(self.request)['target_fingerprint']
        oid=next(iter(self.case['after']))
        def prepare(compiler,request,plan,changes,objects):
            self.prepared(compiler,request,plan,changes,objects)
            compiler.after[oid]=compiler.after[oid].replace(old.encode(),new.encode())
        context_read=commit.contexts.read
        for empty_descriptor in (False,True):
            def read(*args,**kwargs):
                frame=context_read(*args,**kwargs)
                if empty_descriptor:frame.saved[0][15]=s.atom('',True)
                return frame
            with self.subTest(empty_descriptor=empty_descriptor),mock.patch.object(commit.contexts,'read',side_effect=read),mock.patch.object(ibcmd_backend.Compiler,'prepare',autospec=True,side_effect=prepare),mock.patch.object(commit.packets,'assemble',wraps=commit.packets.assemble) as assemble:
                result=commit.serialize(self.request)
                record=next(row for row in assemble.call_args.args[1] if row.object_id==oid)
                metadata=s.Parser(record.metadata.decode('utf-8-sig')).documents()[0]
                self.assertEqual(s.val(metadata[9]),new)
                if empty_descriptor:self.assertEqual(s.val(metadata[15]),'')
                else:self.assertTrue(s.val(metadata[15]).endswith(new))
                self.assertEqual(result['new_ids'],[]);self.assertEqual(result['removed_ids'],[])

    def test_compiler_rebuilt_object_is_included_even_when_its_xml_did_not_change(self):
        objects=metadata_context.context_objects(self.request['context'])
        dependent=next(oid for oid,docs in objects.items() if s.val(docs[0][2])==metadata_identifiers.class_id('Catalog'))
        original_content=ibcmd_backend.Compiler.content
        def prepare(compiler,request,plan,changes,objects):
            self.prepared(compiler,request,plan,changes,objects)
            compiler.before[dependent]=s.native_body_bytes([[s.atom(dependent),s.atom(0)]])
            compiler.after[dependent]=s.native_body_bytes([[s.atom(dependent),s.atom(1)]])
            compiler.delta=compiled_image.Delta(compiler.before,compiler.after,compiler.before,compiler.after,{})
            compiler.object_ids.update(compiler.delta.objects)
        def content(compiler,request,change,objects):
            if change['object_id']!=dependent:return original_content(compiler,request,change,objects)
            frame=serialization_context.read(dict(request,snapshot=request['snapshots'][dependent]),dependent)
            return native_content.ObjectContent(copy.deepcopy(frame.docs),compiler.after[dependent],[],[])
        with mock.patch.object(ibcmd_backend.Compiler,'prepare',autospec=True,side_effect=prepare),mock.patch.object(ibcmd_backend.Compiler,'content',autospec=True,side_effect=content),mock.patch.object(commit.packets,'assemble',wraps=commit.packets.assemble) as assemble:
            result=commit.serialize(self.request)
        self.assertIn(dependent,result['changed_ids'])
        records={row.object_id:row for row in assemble.call_args.args[1]}
        self.assertEqual(len(records),2)
        self.assertEqual(s.inflate(records[dependent].body),s.native_body_bytes([[s.atom(dependent),s.atom(1)]]))

    def test_xml_change_without_native_or_position_change_does_not_make_a_packet(self):
        def prepare(compiler,request,plan,changes,objects):
            self.prepared(compiler,request,plan,changes,objects)
            compiler.after=dict(compiler.before)
            compiler.delta=compiled_image.Delta(compiler.before,compiler.after,compiler.before,compiler.after,{})
        with mock.patch.object(ibcmd_backend.Compiler,'prepare',autospec=True,side_effect=prepare),mock.patch.object(commit.packets,'assemble') as assemble:
            with self.assertRaisesRegex(ValueError,'no native or position changes'):commit.serialize(self.request)
            assemble.assert_not_called()

    def test_stale_repository_version_rejected_before_compilation(self):
        oid = next(iter(self.request['originals']))
        self.request['originals'][oid] = '00' * 20
        with mock.patch.object(ibcmd_backend.Compiler, 'prepare') as prepare:
            with self.assertRaises(ValueError):
                commit.serialize(self.request)
            prepare.assert_not_called()

    def test_context_and_snapshot_mismatch_rejected(self):
        oid = next(iter(self.request['snapshots']))
        frame = serialization_context.read(dict(self.request, snapshot=self.request['snapshots'][oid]), oid)
        current = copy.deepcopy(frame.metadata)
        current[9] = s.atom('Different object', True)
        with self.assertRaisesRegex(ValueError, 'fields=9'):
            serialization_context.validate_metadata(frame.saved[0], current, oid)

    def test_cli_reports_missing_compiler_without_success_payload(self):
        self.request.pop('compiler')
        source = Path(self.temp.name) / 'request.json'
        target = Path(self.temp.name) / 'result.json'
        source.write_text(json.dumps(self.request), encoding='utf-8')
        result = subprocess.run([sys.executable, str(Path(commit.__file__)), str(source), str(target)],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0)
        report = json.loads(target.read_text(encoding='utf-8'))
        self.assertFalse(report['ok'])
        self.assertIn('Compiler requires', report['error'])
        self.assertNotIn('data', report)


if __name__ == '__main__':
    unittest.main()
