"""One addressed module: compiler boundary, immutable object content and fail closed."""
import base64
import copy
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import module_commit as module
import ibcmd_backend
import native_metadata as s
import packet_builder
import cf_container
from test_repository_cache import docs, snapshot, CHILD, ROOT, OLD


def native_module(text, info=b'\xef\xbb\xbf{3,1,0,"",0}'):
    with tempfile.TemporaryFile() as output:
        writer = cf_container.Container()
        writer.file = output
        writer.write_header(2)
        for name, raw in [('info', info), ('text', text.encode('utf-8-sig'))]:
            with tempfile.TemporaryFile() as member:
                member.write(raw)
                member.seek(0)
                writer.add_file(member, name, False)
        writer.write_table_off_content()
        output.seek(0)
        return output.read()


class ModuleCommitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.exe = Path(self.tmp.name)/'compiler.exe'
        self.exe.write_bytes(b'placeholder')
        self.name = CHILD+'.0'
        self.other = CHILD+'.1'
        self.source_text = 'Процедура Тест()\r\nКонецПроцедуры\r\n'
        self.streams = {self.name: native_module(self.source_text), self.other: b'untouched opaque stream'}
        self.saved = docs(CHILD, ROOT, streams={name: OLD for name in self.streams})
        self.body = b'{1,"unchanged body"}'
        self.original = uuid.UUID(OLD).bytes_le+bytes(4)
        source = packet_builder.description(self.saved[0], self.original, self.original)
        source.update(version_number=1, self_version_number=1)
        self.request = dict(object_id=CHILD, platform='8.5.1.1529', repository='test', repository_version=OLD,
                            snapshot=snapshot(CHILD, self.saved, self.body, self.streams), source=source,
                            module_path='Ext/ObjectModule.bsl', module_text='Процедура НовыйТест()\r\nКонецПроцедуры\r\n',
                            compiler=dict(backend='ibcmd', executable=str(self.exe)))

    def overlay(self, compiler, *args):
        self.assertEqual(args[:2], ('cf', 'overlay'))
        before = ibcmd_backend.read_fragment(args[2])
        self.assertEqual(set(before), {self.name, 'versions'})
        name, path = args[-1].split('=', 1)
        self.assertEqual(name, self.name)
        target = Path(path).read_bytes().decode('utf-8-sig')
        ibcmd_backend.write_fragment(args[3], dict(before, **{name: native_module(target)}))
        return dict(ok=True)

    def prepare(self, request=None, overlay=None):
        with mock.patch.object(ibcmd_backend.Compiler, 'execute', autospec=True, side_effect=overlay or self.overlay):
            return module.prepare(request or self.request)

    def test_one_final_packet_preserves_exact_body_metadata_and_other_stream_versions(self):
        self.request['expected_source_sha256'] = hashlib.sha256(self.source_text.encode('utf-8')).hexdigest()
        with mock.patch.object(module.packet_builder, 'assemble', wraps=packet_builder.assemble) as assemble:
            result = self.prepare()
        self.assertEqual(assemble.call_count, 1)
        obj = assemble.call_args[0][1][0]
        self.assertEqual(obj.body, s.compress(self.body))
        self.assertEqual([name for name, _ in obj.externals], [self.name])
        m = s.Parser(obj.metadata.decode('utf-8-sig')).documents()[0]
        for index in (1,2,3,4,9,10,12,13,14,15,16):
            self.assertEqual(s.render(m[index]), s.render(self.saved[0][index]))
        self.assertEqual([(v['name'], v['action']) for v in result['externals']], [(self.name,1),(self.other,0)])
        self.assertEqual(result['externals'][1]['version'], self.original.hex())
        self.assertEqual(result['changed_ids'], [CHILD])
        self.assertFalse(result['new_ids'] or result['removed_ids'])
        self.assertFalse(result['review']['captured'] or result['review']['committed'])

    def test_noop_returns_no_packet_and_does_not_invoke_compiler(self):
        request = dict(self.request, module_text=self.source_text)
        with mock.patch.object(ibcmd_backend.Compiler, 'execute') as execute:
            result = module.prepare(request)
        execute.assert_not_called()
        self.assertFalse(result['has_changes'])
        self.assertNotIn('data', result)
        self.assertEqual(result['review']['diff'], '')

    def test_source_hash_is_checked_before_compilation_even_for_noop(self):
        for target in (self.request['module_text'], self.source_text):
            with mock.patch.object(ibcmd_backend.Compiler, 'execute') as execute:
                with self.assertRaisesRegex(ValueError, 'hash differs'):
                    module.prepare(dict(self.request, expected_source_sha256='0'*64, module_text=target))
            execute.assert_not_called()

    def test_stale_descriptor_rejects_changes_to_identity_names_versions_and_graph_position(self):
        for key, value in dict(name='renamed', pos=1, original='0'*40, local='0'*40,
                               class_id=ROOT, parent_id=CHILD, owner_id=ROOT,
                               version_number=2, self_version_number=2).items():
            request = copy.deepcopy(self.request)
            request['source'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.prepare(request)

    def test_missing_corrupt_incomplete_and_foreign_snapshots_are_rejected(self):
        candidates = ['bad base64', base64.b64encode(base64.b64decode(self.request['snapshot'])[:-2]).decode(),
                      snapshot(CHILD, self.saved, self.body, {self.name: self.streams[self.name]}),
                      snapshot(ROOT, docs(ROOT, s.ZERO), self.body)]
        for candidate in candidates:
            with self.subTest(candidate=candidate[:12]), self.assertRaises((ValueError, KeyError)):
                self.prepare(dict(self.request, snapshot=candidate))

    def test_module_routes_are_exact_and_forms_do_not_fall_back_to_raw_assets(self):
        for path in ('Ext/Unknown.bsl','Ext/Form.xml','Ext/../Ext/ObjectModule.bsl', 'Ext\\ObjectModule.bsl','/Ext/ObjectModule.bsl'):
            with self.subTest(path=path), self.assertRaises(ValueError): self.prepare(dict(self.request, module_path=path))
        for kind in ('CatalogForm','CommonForm'):
            with self.assertRaises(ValueError): module.route(kind, 'Ext/Form/Module.bsl')

    def test_missing_existing_module_is_not_implicitly_created(self):
        request = dict(self.request, snapshot=snapshot(CHILD, docs(CHILD,ROOT), self.body))
        request['source'] = dict(self.request['source'])
        with self.assertRaisesRegex(ValueError, 'absent'):
            self.prepare(request)

    def test_binary_modules_and_oversized_or_nul_bsl_are_rejected(self):
        streams = dict(self.streams, **{self.name: b'protected binary'})
        with self.assertRaisesRegex(ValueError, 'Protected'):
            self.prepare(dict(self.request, snapshot=snapshot(CHILD, self.saved, self.body, streams)))
        for target in ('a\0b', 'x'*32):
            with mock.patch.object(module, 'MAX_MODULE_BYTES', 16), self.assertRaises(ValueError):
                self.prepare(dict(self.request, module_text=target))

    def test_compiler_errors_readback_mismatches_and_extra_members_do_not_produce_packets(self):
        def extra(compiler, *args):
            image = ibcmd_backend.read_fragment(args[2])
            image['unexpected'] = b'foreign'
            ibcmd_backend.write_fragment(args[3], image)
        def unchanged(compiler, *args):
            ibcmd_backend.write_fragment(args[3], ibcmd_backend.read_fragment(args[2]))
        def companion(compiler, *args):
            image = ibcmd_backend.read_fragment(args[2])
            image[self.name] = native_module(self.request['module_text'], info=b'changed companion')
            ibcmd_backend.write_fragment(args[3], image)
        for callback in (extra, unchanged, companion, mock.Mock(side_effect=ValueError('compiler refused'))):
            with mock.patch.object(module.packet_builder, 'assemble') as assemble:
                with self.assertRaises(ValueError): self.prepare(overlay=callback)
            assemble.assert_not_called()

    def test_fragment_never_passes_as_complete_cf_and_compiler_requires_no_supplied_base(self):
        path = Path(self.tmp.name)/'fragment.cf'
        ibcmd_backend.write_fragment(path, module.fragment(self.name, self.streams[self.name], OLD))
        with self.assertRaisesRegex(ValueError, 'Incomplete'): ibcmd_backend.read_cf(path)
        with self.assertRaisesRegex(ValueError, 'no base CF'):
            self.prepare(dict(self.request, compiler=dict(self.request['compiler'], base_cf=str(path))))

    @unittest.skipUnless(os.environ.get('CRS_IBCMD_TEST_EXE'), 'Real compiler not selected')
    def test_real_ibcmd_overlay_on_an_addressed_fragment(self):
        request = dict(self.request, compiler=dict(backend='ibcmd', executable=os.environ['CRS_IBCMD_TEST_EXE']))
        result = module.prepare(request)
        self.assertTrue(result['has_changes'])
        self.assertEqual(result['review']['changed_streams'], [self.name])


if __name__ == '__main__': unittest.main()
