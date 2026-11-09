"""Readable diffs delegate conversion and refuse partial compiler results."""
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_repository_cache import snapshot, docs, ROOT, CHILD
import metadata_identifiers
import native_metadata as s
import object_xml_changes as view


def frame(oid, parent, kind=None, name='Object'):
    description = docs(oid, parent)
    if kind: description[0][2] = s.atom(metadata_identifiers.class_id(kind))
    description[0][9] = s.atom(name, True)
    return snapshot(oid, description, b'body')


class ObjectXMLChangesTests(unittest.TestCase):
    def context(self): return [frame(ROOT, s.ZERO), frame(CHILD, ROOT)]

    def test_minimal_context_names_and_missing_ancestor(self):
        image, name = view.rows(self.context(), CHILD)
        self.assertEqual(name, 'Catalog.Object')
        self.assertEqual(set(image), {ROOT, CHILD, 'root', 'version', 'versions'})
        with self.assertRaises(view.ExportUnavailable): view.rows([frame(CHILD, ROOT)], CHILD)
        with self.assertRaises(ValueError): view.rows(self.context()*2, CHILD)

    def test_form_uses_owner_chain_without_other_objects(self):
        form_id = '66666666-6666-4666-8666-666666666666'
        _, name = view.rows(self.context()+[frame(form_id, CHILD, 'CatalogForm', 'ItemForm')], form_id)
        self.assertEqual(name, 'Catalog.Object.Form.ItemForm')

    def test_xml_properties_keep_stable_element_identity(self):
        before = b'<Form><Items><Field id="1" name="A"/><Field id="2" name="B"/></Items></Form>'
        reordered = b'<Form><Items><Field id="2" name="B"/><Field id="1" name="A"/></Items></Form>'
        self.assertEqual(view.properties(before), view.properties(reordered))
        after = before.replace(b'name="A"', b'name="Changed"')
        a, b = view.properties(before), view.properties(after)
        changed = [key for key in a if a[key] != b[key]]
        self.assertEqual(changed, ['Form/Items[1]/Field[id=1]/@name'])
        with self.assertRaises(ValueError): view.properties(b'<Form><F id="1"/><F id="1"/></Form>')
        with self.assertRaises(ValueError): view.properties(b'<!DOCTYPE F><F/>')

    def request(self, executable):
        return dict(object_id=CHILD, executable=str(executable), platform='8.5.1.1529', before=self.context(), after=self.context())

    def test_readable_module_properties_and_binary_without_native_profiles(self):
        old = {'Object.xml': b'<Object><Properties><Comment>old</Comment></Properties></Object>',
               'Ext/Module.bsl': b'old\n', 'Ext/Image.bin': b'\0\xff'}
        new = {'Object.xml': b'<Object><Properties><Comment>new</Comment></Properties></Object>',
               'Ext/Module.bsl': b'new\n', 'Ext/Image.bin': b'\0\xfe'}
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory)/'ibcmd'; exe.write_bytes(b'fake')
            with patch.object(view, 'export', side_effect=[old, new]): result = view.compare(self.request(exe))
        self.assertEqual(result['status'], 'available')
        files = {r['path']: r for r in result['files']}
        self.assertIn('-old\n+new\n', files['Ext/Module.bsl']['diff'])
        self.assertEqual(files['Object.xml']['properties'], [dict(path='Object/Properties[1]/Comment[1]', before='old', after='new')])
        self.assertEqual(files['Ext/Image.bin']['after']['format'], 'binary')

    def test_creation_deletion_and_failure_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory)/'ibcmd'; exe.write_bytes(b'fake')
            for absent, action in [('before', 'create'), ('after', 'delete')]:
                request = self.request(exe); request[absent] = None
                with patch.object(view, 'export', return_value={'Ext/Module.bsl': b'code'}): result = view.compare(request)
                self.assertEqual(result['files'][0]['action'], action)
            with patch.object(view, 'export', side_effect=view.ExportUnavailable('unsupported property')):
                result = view.compare(self.request(exe))
            self.assertEqual(result, dict(status='unavailable', side='before', reason='unsupported property', representation='xml'))

    def test_export_checks_asset_coverage_and_selected_uuid(self):
        good = dict(tables=[dict(source_assets=dict(status='complete', candidate_set_complete=True,
                        expected=0, emitted=0, opaque=0, missing=0, opaque_property_count=0))])
        def run_case(report, written, raw):
            with tempfile.TemporaryDirectory() as directory:
                work = Path(directory)/'work'
                def compiler(args, **kwargs):
                    if args[1] == 'mssql-dump-config': return subprocess.CompletedProcess(args, 0, json.dumps(report).encode(), b'')
                    target = Path(args[args.index('--target-dir')+1]); target.mkdir()
                    if written:
                        (target/'Object.xml').write_bytes(raw)
                    response = dict(objects=[dict(object='Catalog.Object', written=written)])
                    return subprocess.CompletedProcess(args, 0, json.dumps(response).encode(), b'')
                with patch.object(view.subprocess, 'run', side_effect=compiler), patch.object(view.object_view_context, 'plan', return_value=dict(collections=[], references=[])):
                    return view.export(Path('ibcmd'), '8.5.1.1529', self.context(), CHILD, work)
        xml = ('<MetaDataObject xmlns="urn:test"><Catalog uuid="'+CHILD+'"/></MetaDataObject>').encode()
        self.assertEqual(run_case(good, ['Object.xml'], xml), {'Object.xml': xml})
        for written, raw in [([], xml), (['Object.xml'], b'<Other/>')]:
            with self.assertRaises(view.ExportUnavailable): run_case(good, written, raw)
        bad = json.loads(json.dumps(good)); bad['tables'][0]['source_assets']['opaque_property_count'] = 1
        with self.assertRaises(view.ExportUnavailable): run_case(bad, ['Object.xml'], xml)
        bad = json.loads(json.dumps(good)); bad['tables'][0]['source_assets']['expected'] = 1
        with self.assertRaises(view.ExportUnavailable): run_case(bad, ['Object.xml'], xml)
        with self.assertRaises(ValueError): run_case(good, ['../Object.xml'], xml)

    def test_cycles_and_non_configuration_root_are_rejected(self):
        form_id = '66666666-6666-4666-8666-666666666666'
        with self.assertRaises(ValueError):
            view.rows([frame(ROOT, s.ZERO), frame(CHILD, form_id), frame(form_id, CHILD, 'CatalogForm')], CHILD)
        with self.assertRaises(ValueError):
            view.rows([frame(ROOT, s.ZERO, 'Catalog'), frame(CHILD, ROOT)], CHILD)

    def test_invalid_executable_is_not_an_empty_diff(self):
        with self.assertRaises(ValueError): view.compare(self.request(Path('/nonexistent/ibcmd')))
