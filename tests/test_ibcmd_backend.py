"""Compiler admission, effective CF images and lossless XML staging."""
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import types
import unittest
from unittest import mock

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))

import ibcmd_backend as backend
import native_metadata as s


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.exe = self.root / 'ibcmd.exe'
        self.exe.write_bytes(b'placeholder')
        self.base = self.root / 'base.cf'
        self.image = {'root': b'root', 'version': b'version', 'versions': b'versions', 'object': b'original'}
        backend.write_cf(self.base, self.image)
        self.request = {'compiler': dict(backend='ibcmd', executable=str(self.exe), base_cf=str(self.base))}

    def compiler(self):
        return backend.Compiler(self.request)

    def test_diagnostic_verification_override_never_reaches_the_compiler(self):
        with mock.patch.dict(backend.os.environ,{'IBCMD_RS_LOAD_NO_VERIFY':'1'}),mock.patch.object(backend.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'diagnostic mode'):
                self.compiler().execute('cf','load','source','target')
            run.assert_not_called()

    def test_cf_normalization_preserves_all_records(self):
        self.assertEqual(backend.read_cf(self.base), self.image)

    def test_last_container_is_effective_and_does_not_merge_compatibility_objects(self):
        from cf_container import Container64
        image = dict(self.image, object=b'active')
        image.pop('object')
        image['active'] = b'new'
        path = self.root / 'dual.cf'
        compatibility = self.base.read_bytes()
        from cf_container import detect_format
        with self.base.open('rb') as source:
            first = detect_format(source, 0)
            first.read(source, 0)
            for item in first.files.values():
                b''.join(item.data)
        # Match the fixed-block image extent reported by the container reader.
        compatibility += bytes(max(0, first.size - len(compatibility)))
        # A real Format16 header has an offset, not a Format15-style magic.
        with tempfile.TemporaryFile() as buffer:
            writer = Container64()
            writer.file = buffer
            writer.write_header(len(image))
            for name, value in image.items():
                with tempfile.TemporaryFile() as item:
                    item.write(s.compress(value)); item.seek(0)
                    writer.add_file(item, name, False)
            writer.write_table_off_content()
            buffer.seek(0)
            active = bytearray(buffer.read())
            struct.pack_into('<Q', active, 0, 100)
        path.write_bytes(compatibility + active)
        self.assertEqual(backend.read_cf(path), image)

    def test_missing_cf_and_non_cf_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Missing'):
            backend.read_cf(self.root / 'missing.cf')
        self.base.write_bytes(b'not a configuration')
        with self.assertRaisesRegex(ValueError, 'header'):
            backend.read_cf(self.base)

    def test_unused_namespace_is_aligned_without_changing_complete_xml(self):
        text = '<Form xmlns="urn:form" xmlns:unused="urn:unused"><Title>Entire file</Title></Form>'
        template = '<Form xmlns="urn:form"><Title>old</Title></Form>'
        result = backend.align_xml(text, template)
        self.assertNotIn('unused', result)
        self.assertIn('Entire file', result)
        self.assertEqual(backend.canonical(text), backend.canonical(result))

    def test_used_qname_binding_cannot_be_discarded_or_rebound(self):
        text = '<Form xmlns="urn:form" xmlns:cfg="urn:cfg"><Type>cfg:CatalogRef.Test</Type></Form>'
        for template in ('<Form xmlns="urn:form"/>', '<Form xmlns="urn:form" xmlns:cfg="urn:other"/>'):
            with self.assertRaisesRegex(ValueError, 'namespace'):
                backend.align_xml(text, template)
        with self.assertRaisesRegex(ValueError, 'namespace'):
            backend.align_xml("<Form xmlns='urn:form' xmlns:cfg='urn:cfg'><Type>cfg:CatalogRef.Test</Type></Form>",
                              '<Form xmlns="urn:form" xmlns:cfg="urn:other"/>')

    def test_xml_header_attributes_and_doctype_cannot_be_silently_changed(self):
        with self.assertRaisesRegex(ValueError, 'changed'):
            backend.align_xml('<Form version="2.21"/>', '<Form version="2.20"/>')
        with self.assertRaisesRegex(ValueError, 'DOCTYPE'):
            backend.canonical('<!DOCTYPE Form><Form/>')

    def test_invalid_backend_and_unknown_options_are_rejected(self):
        for options in ({'backend': 'other'}, dict(self.request['compiler'], unexpected=True)):
            with self.assertRaisesRegex(ValueError, 'requires'):
                backend.Compiler({'compiler': options})

    def test_external_process_is_argv_and_has_a_bounded_timeout(self):
        result = types.SimpleNamespace(returncode=0, stdout=b'{"ok":true}', stderr=b'')
        with mock.patch.object(backend.subprocess, 'run', return_value=result) as execute:
            self.compiler().execute('cf', 'load', 'a path/with spaces')
        args, kwargs = execute.call_args
        self.assertEqual(args[0], [str(self.exe), 'cf', 'load', 'a path/with spaces'])
        self.assertEqual(kwargs['timeout'], 240)
        self.assertNotIn('shell', kwargs)

    def test_rejected_overlay_uses_base_free_compiler_and_preserves_bound_service_headers(self):
        with self.compiler() as compiler:
            source=compiler.work/'source';source.mkdir();(source/'Configuration.xml').write_text('whole target')
            (source/'.ibcmd').mkdir();(source/'.ibcmd/index.tsv').write_text('overlay index')
            candidate=dict(self.image,version=b'bootstrap selector',object=b'compiled target')
            def execute(*args):
                if args[:2]==('cf','load'):raise backend.CompilationRejected('missing nested entry')
                self.assertEqual(args[:2],('cf','bootstrap'))
                self.assertEqual(Path(args[2]).joinpath('Configuration.xml').read_text(),'whole target')
                self.assertFalse(Path(args[2]).joinpath('.ibcmd').exists())
                backend.write_cf(Path(args[3]),candidate)
            output=compiler.work/'target.cf'
            with mock.patch.object(compiler,'execute',side_effect=execute):
                compiler.compile_tree(source,self.base,output,self.image,'8.5.1.1529')
            self.assertEqual(compiler.route,'bootstrap')
            self.assertEqual(backend.read_cf(output),dict(candidate,version=self.image['version']))

    def test_base_free_cannot_change_root_and_cannot_hide_two_rejections(self):
        for foreign in (True,False):
            with self.subTest(foreign=foreign),self.compiler() as compiler:
                source=compiler.work/'source';source.mkdir()
                def execute(*args):
                    if args[:2]==('cf','load'):raise backend.CompilationRejected('overlay rejection')
                    if not foreign:raise backend.CompilationRejected('bootstrap rejection')
                    backend.write_cf(Path(args[3]),dict(self.image,root=b'foreign root'))
                with mock.patch.object(compiler,'execute',side_effect=execute):
                    with self.assertRaisesRegex(ValueError,'root identity' if foreign else 'overlay rejection.*bootstrap rejection'):
                        compiler.compile_tree(source,self.base,compiler.work/'target.cf',self.image,'8.5.1.1529')

    def test_base_free_assembly_is_followed_by_full_export_verification(self):
        for matches in (True,False):
            with self.subTest(matches=matches),self.compiler() as compiler:
                source=compiler.work/'source';source.mkdir();events=[]
                def execute(*args):
                    if args[:2]==('cf','load'):raise backend.CompilationRejected('overlay rejected')
                    backend.write_cf(Path(args[3]),self.image)
                def assemble(image):
                    events.append('assemble');return dict(image,object=b'preserved source')
                def verify(path):
                    events.append('verify');self.assertEqual(backend.read_cf(path)['object'],b'preserved source')
                    if not matches:raise backend.ExportMismatch('target still differs')
                with mock.patch.object(compiler,'execute',side_effect=execute):
                    if matches:compiler.compile_tree(source,self.base,compiler.work/'out.cf',self.image,'8.5.1.1529',verify,assemble)
                    else:
                        with self.assertRaisesRegex(backend.CompilationRejected,'target still differs'):
                            compiler.compile_tree(source,self.base,compiler.work/'out.cf',self.image,'8.5.1.1529',verify,assemble)
                self.assertEqual(events,['assemble','verify'])

    def test_base_free_preserves_all_records_only_for_completely_unchanged_owners(self):
        records={'object':dict(path='Object.xml',files=['Object.xml','Object/Module.bsl']),
                 'other':dict(path='Other.xml',files=['Other.xml','Other/Form.xml'])}
        files={'Object.xml':b'<Object>old</Object>','Object/Module.bsl':b'old module','Other.xml':b'<Other/>','Other/Form.xml':b'<Form/>'}
        before=dict(self.image,other=b'original other',**{'other.0':b'original form','other.1':b'original binary'})
        candidate=dict(self.image,object=b'compiled edit',other=b'normalized other',**{'other.0':b'normalized form','other.extra':b'compiler addition'})
        target=dict(files,**{'Object.xml':b'<Object>edited</Object>'})
        result=backend.retain_unchanged_objects(before,candidate,records,records,{},files,target)
        self.assertEqual(result,dict(before,object=b'compiled edit'))
        # A companion-only edit makes the owner changed too; none of its
        # native streams may be silently restored from the source.
        target['Other/Form.xml']=b'<Form>edited</Form>'
        self.assertEqual(backend.retain_unchanged_objects(before,candidate,records,records,{},files,target),candidate)
        candidate['unclassified']=b'cannot be hidden'
        with self.assertRaisesRegex(ValueError,'Unclassified native CF record'):
            backend.retain_unchanged_objects(before,candidate,records,records,{},files,target)

    def test_base_free_keeps_unchanged_owner_despite_xml_and_module_formatting(self):
        records={'object':dict(path='Object.xml',files=['Object.xml','Object/Module.bsl'])}
        files={'Object.xml':b'<Object><Name>Same</Name></Object>','Object/Module.bsl':b'// unchanged\r\n'}
        target={'Object.xml':b'\xef\xbb\xbf<Object>\n  <Name>Same</Name>\n</Object>','Object/Module.bsl':b'\xef\xbb\xbf// unchanged\n'}
        candidate=dict(self.image,object=b'compiler normalization',**{'object.0':b'new stream'})
        self.assertEqual(backend.retain_unchanged_objects(self.image,candidate,records,records,{},files,target),self.image)

    def test_invalid_reports_and_timeouts_do_not_trigger_another_route(self):
        with self.compiler() as compiler,mock.patch.object(compiler,'execute',side_effect=ValueError('invalid JSON')) as execute:
            with self.assertRaisesRegex(ValueError,'invalid JSON'):
                compiler.compile_tree(compiler.work/'source',self.base,compiler.work/'out.cf',self.image,'8.5.1.1529')
            self.assertEqual(execute.call_count,1)

    def test_no_changes_does_not_rebuild_unchanged_configuration(self):
        with self.compiler() as compiler,mock.patch.object(compiler,'execute',side_effect=backend.CompilationRejected('no changes',['no_changes'])) as execute:
            with self.assertRaisesRegex(ValueError,'no changes'):
                compiler.compile_tree(compiler.work/'source',self.base,compiler.work/'out.cf',self.image,'8.5.1.1529')
            self.assertEqual(execute.call_count,1)

    def test_successful_overlay_with_wrong_output_rebuilds_and_reverifies_the_target(self):
        for bootstrap_matches in (True,False):
            with self.subTest(bootstrap_matches=bootstrap_matches),self.compiler() as compiler:
                source=compiler.work/'source';source.mkdir();routes=[]
                def execute(*args):
                    if args[:2]==('cf','bootstrap'):backend.write_cf(Path(args[3]),self.image)
                def verify(path):
                    routes.append(compiler.route)
                    if compiler.route=='overlay' or not bootstrap_matches:raise backend.ExportMismatch('wrong target XML')
                with mock.patch.object(compiler,'execute',side_effect=execute):
                    if bootstrap_matches:
                        compiler.compile_tree(source,self.base,compiler.work/'out.cf',self.image,'8.5.1.1529',verify)
                    else:
                        with self.assertRaisesRegex(ValueError,'base-free verification'):
                            compiler.compile_tree(source,self.base,compiler.work/'out.cf',self.image,'8.5.1.1529',verify)
                self.assertEqual(routes,['overlay','bootstrap'])

    def test_complete_export_cannot_gain_drop_or_change_an_unrequested_binary(self):
        output=self.root/'exported';output.mkdir()
        xml=b'<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.21"><Configuration uuid="11111111-1111-4111-8111-111111111111"><Properties><Name>Cfg</Name></Properties><ChildObjects/></Configuration></MetaDataObject>'
        (output/'Configuration.xml').write_bytes(xml);(output/'Ext').mkdir()
        target={'Configuration.xml':xml,'Ext/data.bin':b'\x00\xff'}
        binary=output/'Ext/data.bin';binary.write_bytes(target['Ext/data.bin'])
        backend.verify_export(target,output)
        binary.write_bytes(b'wrong bytes')
        with self.assertRaisesRegex(ValueError,'differs from target XML/file'):backend.verify_export(target,output)
        binary.unlink()
        with self.assertRaisesRegex(ValueError,'file set differs'):backend.verify_export(target,output)
        binary.write_bytes(target['Ext/data.bin']);(output/'Ext/extra.bin').write_bytes(b'unrequested')
        with self.assertRaisesRegex(ValueError,'file set differs'):backend.verify_export(target,output)

    def test_failed_or_invalid_compiler_reports_and_timeouts_are_rejected(self):
        for result in (types.SimpleNamespace(returncode=2, stdout=b'{"ok":false,"errors":[{"message":"unsupported form"}]}'),
                       types.SimpleNamespace(returncode=0, stdout=b'not JSON')):
            with mock.patch.object(backend.subprocess, 'run', return_value=result), self.assertRaises(ValueError):
                self.compiler().execute('cf', 'load')
        with mock.patch.object(backend.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ibcmd', 240)):
            with self.assertRaisesRegex(ValueError, 'timed out'):
                self.compiler().execute('cf', 'load')

    def test_compiler_has_no_per_class_xml_admission_policy(self):
        with mock.patch.object(backend.subprocess,'run') as execute,mock.patch.object(backend.configuration_export,'inventory',return_value=(self.root,{}, {},None)),mock.patch.object(backend,'read_cf',side_effect=RuntimeError('admitted')):
            with self.assertRaisesRegex(RuntimeError,'admitted'):
                self.compiler().prepare(dict(directory=str(self.root)),dict(new_ids=['new'],removed_ids=[]),[dict(kind='Constant',object_id='new')],{})
            execute.assert_not_called()

    def test_structured_error_on_stderr_is_reported(self):
        result = types.SimpleNamespace(returncode=2, stdout=b'', stderr=b'{"ok":false,"errors":[{"message":"unsupported Document layout"}]}')
        with mock.patch.object(backend.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(ValueError, 'unsupported Document layout'):
                self.compiler().execute('cf', 'load')

    def test_stale_base_object_is_rejected_before_execution(self):
        request = dict(self.request, snapshots={'object': 'snapshot'})
        frame = types.SimpleNamespace(data=s.compress(b'changed on repository'))
        for removed in ([],['object']):
            plan=dict(new_ids=[],removed_ids=removed,snapshot_ids=['object'])
            with self.subTest(removed=removed),mock.patch.object(backend.serialization_context,'read',return_value=frame),mock.patch.object(backend.subprocess,'run') as execute:
                with self.assertRaisesRegex(ValueError,'Stale or foreign.*object'):
                    self.compiler().prepare(request,plan,[],{})
                execute.assert_not_called()

    def test_implicit_dependent_form_cannot_receive_an_uncompiled_stream(self):
        compiler = self.compiler()
        compiler.object_ids = {'planned-catalog'}
        with self.assertRaisesRegex(ValueError, 'implicit dependent-object'):
            compiler.content({}, {'object_id': 'additional-dependent-form'}, {})

    def test_compiler_workspace_is_removed_on_failure(self):
        with self.assertRaisesRegex(ValueError, 'failure'):
            with self.compiler() as compiler:
                directory = compiler.work
                (directory / 'input').write_bytes(b'data')
                raise ValueError('failure')
        self.assertFalse(directory.exists())


if __name__ == '__main__':
    unittest.main()
