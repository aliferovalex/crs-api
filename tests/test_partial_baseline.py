"""Incomplete XML cannot delete/replace the complete native configuration."""
import copy
from contextlib import nullcontext
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
import uuid
from xml.etree import ElementTree as ET
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import configuration_export as export
import ibcmd_backend
import partial_baseline as partial
import repository_baseline as baseline
import repository_cache
import resource_limits


class PartialBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.work=Path(self.temp.name);self.cache=self.work/'cache';self.identity='a'*32
        fixture=Path(__file__).with_name('fixtures')/'ibcmd_document'
        request=json.loads((fixture/'request.json').read_text(encoding='utf-8'))['request']
        root,objects,_=repository_cache.inventory(request['context'])
        self.state=dict(schema=1,generation='b'*32,root_id=root,objects=objects,platform=request['platform'],
                        repository_id='77777777-7777-4777-8777-777777777777',
                        repository_version='55555555-5555-4555-8555-555555555555',cf_sha256=repository_cache.digest(b'complete CF'))
        self.cf=self.cache/'generations'/self.state['generation']/'base.cf'
        self.cf.parent.mkdir(parents=True);self.cf.write_bytes(b'complete CF')
        self.folder=self.cache/'baselines'/self.identity;self.xml=self.folder/'xml'
        shutil.copytree(fixture/'baseline',self.xml)
        _,files,records,_=export.inventory(self.xml)
        self.missing=next(oid for oid,row in records.items() if row['kind']=='Constant')
        (self.xml/records[self.missing]['path']).unlink()
        self.selected=next(oid for oid,row in records.items() if row['kind']=='Document')
        stream=self.selected+'.0';version=objects[self.selected]['local']
        objects[self.selected]['externals'][stream]=version
        module=records[self.selected]['path'][:-4]+'/Ext/ObjectModule.bsl'
        (self.xml/module).parent.mkdir(parents=True);(self.xml/module).write_bytes(b'// original\r\n')
        records[self.selected]['files'].append(module);files[module]=b'// original\r\n'
        dump=self.xml/'ConfigDumpInfo.xml';tree=ET.parse(dump)
        ET.SubElement(tree.getroot(),export.D+'Metadata',dict(id=stream,configVersion=uuid.UUID(version).bytes_le.hex()+'00000000'))
        tree.write(dump,encoding='utf-8',xml_declaration=True)
        image={oid:b'unchanged native body' for oid in objects}
        image[stream]=b'unchanged native module'
        image['root']=('{2,'+root+'}').encode();image['version']=b'{1,0}'
        image['versions']=repository_cache.service_versions(image,objects)
        ibcmd_backend.write_cf(self.cf,image)
        self.state['cf_sha256']=repository_cache.digest(self.cf.read_bytes())
        rows=[dict(logical_name=name,logical_key=name,part_count=1,disposition='opaque',outputs=[])
              for name in sorted(repository_cache.SERVICE)]
        for oid,row in objects.items():
            definition=records[oid]['path']
            rows.append(dict(logical_name=oid,logical_key=oid,part_count=1,
                             disposition='opaque' if oid==self.missing else 'supported',
                             outputs=[] if oid==self.missing else [definition]))
            companions=[n for n in records[oid]['files'] if n!=definition]
            for index,name in enumerate(row['externals']):
                rows.append(dict(logical_name=name,logical_key=name,part_count=1,disposition='supported',
                                 outputs=companions if index==0 else []))
        self.rows=rows
        self.report=dict(schema_version=1,command='export',ok=True,input=str(self.cf),output_dir=str(self.xml),errors=[],
                         export=dict(files_written=len(files)-1,storage=dict(schema_version=1,physical_entries=len(rows),
                                     logical_entries=len(rows),entries=rows)))
        self.recount()
        self.report_path=self.work/'report.json';self.save_report()
        self.request=dict(mode='adopt_partial',cache_directory=str(self.cache),generation=self.state['generation'],
                          snapshot_id=self.identity,report_file=str(self.report_path),working_directory=str(self.work/'working'))

    def recount(self):
        storage=self.report['export']['storage']
        for status in ('supported','opaque','failed'):storage[status]=sum(r['disposition']==status for r in self.rows)
        self.report['ok']=not storage['failed']
        self.report['errors']=[] if self.report['ok'] else [dict(code='entry_export_failed',message='One failed entry')]

    def save_report(self):self.report_path.write_text(json.dumps(self.report),encoding='utf-8')

    def initialize(self,**extra):
        self.save_report()
        with mock.patch.object(repository_cache.Cache,'load_state',return_value=(copy.deepcopy(self.state),self.cf)),\
             mock.patch.object(repository_cache.Cache,'load',side_effect=AssertionError('Complete native image must not be decoded')):
            return baseline.run(dict(self.request,**extra))

    def test_sparse_basis_keeps_missing_owner_and_complete_cf(self):
        cf=self.cf.read_bytes();result=self.initialize()
        self.assertEqual(result['kind'],'partial');self.assertFalse(result['automatic_deletion'])
        self.assertEqual(self.cf.read_bytes(),cf)
        data=json.loads(Path(result['coverage_file']).read_text(encoding='utf-8'))
        self.assertEqual(data['objects'][self.missing]['representation'],'unavailable')
        self.assertEqual(set(data['objects']),set(self.state['objects']))
        working=Path(result['working_directory'])
        self.assertEqual(set(p.name for p in working.iterdir()),{'Configuration.xml','ConfigDumpInfo.xml',partial.MARKER})
        self.assertEqual(baseline.read(self.cache),result)
        with self.assertRaisesRegex(ValueError,'Partial XML'):export.inventory(working)
        with self.assertRaisesRegex(ValueError,'Partial XML'):export.inventory(self.xml)

    def test_materialize_copies_owner_and_companions_without_overwrite(self):
        result=self.initialize();req=dict(cache_directory=str(self.cache),baseline_id=result['baseline_id'],object_ids=[self.selected])
        copied=partial.materialize(req);self.assertTrue(copied['copied_files'])
        self.assertFalse(copied['captured']);self.assertFalse(copied['committed'])
        self.assertEqual(partial.materialize(req)['copied_files'],[])
        path=Path(result['working_directory'])/copied['copied_files'][0]
        frozen=(self.xml/copied['copied_files'][0]).read_bytes();path.write_bytes(b'local edit')
        with self.assertRaisesRegex(ValueError,'local changes'):partial.materialize(req)
        self.assertEqual((self.xml/copied['copied_files'][0]).read_bytes(),frozen)
        self.assertEqual(path.read_bytes(),b'local edit')
        # Unavailable owners remain explicitly unavailable; no guessed XML.
        copied=partial.materialize(dict(req,object_ids=[self.missing]))
        self.assertEqual(copied['objects'][self.missing]['representation'],'unavailable')

    def test_failed_asset_does_not_turn_its_owner_into_fully_exported(self):
        asset=next(r for r in self.rows if r['logical_key'] in self.state['objects'][self.selected]['externals'])
        asset['disposition']='failed';asset['outputs']=[];self.recount()
        result=self.initialize();data=json.loads(Path(result['coverage_file']).read_text(encoding='utf-8'))
        self.assertEqual(data['objects'][self.selected]['representation'],'partial')
        self.assertEqual(data['counts']['failed'],1)

    def test_missing_dump_info_uses_native_versions_without_fabricating_xml(self):
        (self.xml/'ConfigDumpInfo.xml').unlink();self.report['export']['files_written']-=1
        result=self.initialize();data=json.loads(Path(result['coverage_file']).read_text(encoding='utf-8'))
        self.assertEqual(data['entries'][self.selected]['version'],self.state['objects'][self.selected]['local'])
        self.assertFalse((Path(result['working_directory'])/'ConfigDumpInfo.xml').exists())
        self.assertEqual(baseline.read(self.cache),result)

    def test_native_versions_are_checked_independently_of_export_report(self):
        image=ibcmd_backend.read_cf(self.cf)
        image['versions']=image['versions'].replace(self.state['objects'][self.selected]['local'].encode(),b'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee')
        ibcmd_backend.write_cf(self.cf,image)
        with self.assertRaisesRegex(ValueError,'versions/root'):self.initialize()
        self.assertFalse((self.cache/'baseline.json').exists())

    def test_wrong_source_versions_report_or_generation_cannot_publish(self):
        for mutation in ('source','versions','entry','error','generation','count','missing-output'):
            with self.subTest(mutation=mutation):
                old_report=copy.deepcopy(self.report);old_xml=(self.xml/'ConfigDumpInfo.xml').read_bytes()
                extra={}
                if mutation=='source':self.report['input']=str(self.work/'other.cf')
                if mutation=='versions':(self.xml/'ConfigDumpInfo.xml').write_bytes(old_xml.replace(b'configVersion="',b'configVersion="f',1))
                if mutation=='entry':self.rows.pop()
                if mutation=='error':self.report['errors']=[dict(code='fatal',message='Broken compiler')]
                if mutation=='generation':extra['generation']='e'*32
                if mutation=='count':self.report['export']['storage']['opaque']+=1
                if mutation=='missing-output':self.rows[-1]['outputs']=['missing.xml']
                try:
                    with self.assertRaises(ValueError):self.initialize(**extra)
                    self.assertFalse((self.cache/'baseline.json').exists())
                    self.assertFalse((self.work/'working').exists())
                finally:
                    self.report=old_report;self.rows=self.report['export']['storage']['entries']
                    (self.xml/'ConfigDumpInfo.xml').write_bytes(old_xml)

    def test_frozen_files_and_coverage_are_checked_before_materializing(self):
        result=self.initialize();path=self.xml/'Configuration.xml';raw=path.read_bytes();path.write_bytes(raw+b'\n')
        with self.assertRaisesRegex(ValueError,'modified'):baseline.read(self.cache)
        path.write_bytes(raw);coverage=Path(result['coverage_file']);coverage.write_bytes(coverage.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'coverage map'):baseline.read(self.cache)

    def test_selected_files_are_verified_lazily_and_full_audit_is_available(self):
        result=self.initialize();data=json.loads(Path(result['coverage_file']).read_text(encoding='utf-8'))
        path=self.xml/data['objects'][self.selected]['definition']['path'];path.write_bytes(path.read_bytes()+b'\n')
        self.assertEqual(baseline.read(self.cache)['baseline_id'],result['baseline_id'])
        with self.assertRaisesRegex(ValueError,'Frozen source'):
            partial.materialize(dict(cache_directory=str(self.cache),baseline_id=result['baseline_id'],object_ids=[self.selected]))
        with self.assertRaisesRegex(ValueError,'modified'):baseline.read(self.cache,verify_all_files=True)

    def test_path_escape_in_report_or_existing_working_directory_is_rejected(self):
        for unsafe in ('../outside.xml','/absolute.xml','C:/escape.xml','dir\\file.xml','x/../bad.xml'):
            with self.subTest(unsafe=unsafe):
                self.rows[-1]['outputs']=[unsafe]
                with self.assertRaisesRegex(ValueError,'path'):self.initialize()
        self.rows[-1]['outputs']=[]
        (self.work/'working').mkdir();sentinel=self.work/'working'/'user.bsl';sentinel.write_bytes(b'user changes')
        with self.assertRaisesRegex(ValueError,'must be new'):self.initialize()
        self.assertEqual(sentinel.read_bytes(),b'user changes')

    def test_entry_failure_is_accepted_only_in_explicit_partial_mode(self):
        # Use the real initialize dispatch and compiler failure contract.
        self.rows[-1]['disposition']='failed';self.rows[-1]['outputs']=[];self.recount()
        exe=self.work/'compiler.exe';exe.touch()
        def execute(compiler,*args):
            shutil.copytree(self.xml,args[3]);report=copy.deepcopy(self.report);report['output_dir']=str(args[3])
            raise ibcmd_backend.CompilationRejected('entry failure',['entry_export_failed'],report)
        request=dict(self.request,mode='initialize',executable=str(exe),allow_partial=True)
        with mock.patch.object(repository_cache.Cache,'load_state',return_value=(self.state,self.cf)),\
             mock.patch.object(ibcmd_backend.Compiler,'execute',autospec=True,side_effect=execute):
            result=baseline.initialize(request)
        self.assertEqual(result['export_counts']['failed'],1)

    def test_limits_apply_to_partial_files_and_fatal_failure_keeps_pointer_absent(self):
        with resource_limits.scope(dict(export_files=1)):
            with self.assertRaisesRegex(ValueError,'limits'):self.initialize()
        exe=self.work/'compiler.exe';exe.touch()
        request=dict(self.request,mode='initialize',executable=str(exe),allow_partial=True)
        with mock.patch.object(repository_cache.Cache,'load_state',return_value=(self.state,self.cf)),\
             mock.patch.object(ibcmd_backend.Compiler,'execute',side_effect=ibcmd_backend.CompilationRejected('fatal',['fatal'],self.report)):
            with self.assertRaisesRegex(ibcmd_backend.CompilationRejected,'fatal'):baseline.initialize(request)
        self.assertFalse((self.cache/'baseline.json').exists())

    def test_file_changed_during_hashing_is_rejected(self):
        digest=resource_limits.file_digest
        def changed(path,*args,**kwargs):
            result=digest(path,*args,**kwargs)
            if Path(path).name=='Configuration.xml':
                with Path(path).open('ab') as output:output.write(b'\n')
            return result
        with mock.patch.object(resource_limits,'file_digest',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'changed while reading'):partial.scan(self.xml)

    def test_metadata_changed_between_scan_and_publication_cannot_publish(self):
        scan=partial.scan
        def changed(directory):
            files=scan(directory)
            with (Path(directory)/'Configuration.xml').open('ab') as output:output.write(b'\n')
            return files
        with mock.patch.object(partial,'scan',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'changed after hashing'):self.initialize()
        self.assertFalse((self.cache/'baseline.json').exists())

    def test_windows_junction_attributes_are_rejected_before_descent(self):
        entry=types.SimpleNamespace(name='junction',path=str(self.xml/'junction'),
                                    stat=lambda **kw:types.SimpleNamespace(st_file_attributes=0x400),
                                    is_symlink=lambda:False)
        with mock.patch.object(partial.os,'scandir',return_value=nullcontext([entry])):
            with self.assertRaisesRegex(ValueError,'reparse point'):partial.scan(self.xml)


if __name__=='__main__':unittest.main()
