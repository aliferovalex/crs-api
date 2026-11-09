"""Frozen XML baselines, optional working directories and failed-publication isolation."""
import base64
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import uuid
from xml.etree import ElementTree as E
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import configuration_export as export
import repository_baseline as baseline
import repository_cache
import native_metadata as s


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.work=Path(self.temp.name);self.cache=self.work/'.crs-cache'
        self.fixture=Path(__file__).with_name('fixtures')/'ibcmd_document'
        request=json.loads((self.fixture/'request.json').read_text(encoding='utf-8'))['request']
        root,objects,_=repository_cache.inventory(request['context'])
        self.state=dict(generation='f'*32,root_id=root,objects=objects,platform=request['platform'],
                        repository_id='77777777-7777-4777-8777-777777777777',
                        repository_version='55555555-5555-4555-8555-555555555555')
        self.cf=self.cache/'generations'/self.state['generation']/'base.cf'
        self.cf.parent.mkdir(parents=True);self.cf.write_bytes(b'placeholder')
        self.exe=self.work/'compiler.exe';self.exe.write_bytes(b'placeholder')
        self.request=dict(cache_directory=str(self.cache),generation=self.state['generation'],executable=str(self.exe))

    def initialize(self,native_image=None,**extra):
        def execute(compiler,*args):
            self.assertEqual(args[:2],('cf','export'))
            shutil.copytree(self.fixture/'baseline',args[3])
        with mock.patch.object(repository_cache.Cache,'load',return_value=(copy.deepcopy(self.state),native_image or {},self.cf)),mock.patch.object(baseline.ibcmd_backend.Compiler,'execute',autospec=True,side_effect=execute):
            return baseline.initialize(dict(self.request,**extra))

    def test_initialize_without_git_and_read_frozen_basis(self):
        result=self.initialize();loaded=baseline.read(self.cache)
        self.assertEqual(loaded,result)
        self.assertEqual(export.inventory(result['working_directory'])[1],export.inventory(result['baseline_directory'])[1])
        self.assertFalse((self.cache/'xml.git').exists())
        file=next((Path(result['working_directory'])/'Catalogs').glob('*.xml'))
        file.write_bytes(file.read_bytes()+b'\n')
        self.assertEqual(baseline.read(self.cache),result)

    def test_existing_current_xml_preserved_and_old_basis_survives_reinitialize(self):
        working=self.work/'existing';shutil.copytree(self.fixture/'baseline',working)
        file=next((working/'Catalogs').glob('*.xml'));file.write_bytes(file.read_bytes()+b'\n')
        original=export.inventory(working)[1]
        first=self.initialize(working_directory=str(working));second=self.initialize(working_directory=str(working))
        self.assertFalse(second['working_directory_created'])
        self.assertEqual(export.inventory(working)[1],original)
        self.assertNotEqual(first['baseline_id'],second['baseline_id'])
        self.assertTrue(Path(first['manifest_file']).is_file())
        self.assertEqual(baseline.read(self.cache)['baseline_id'],second['baseline_id'])

    def test_foreign_versions_fail_without_replacing_active_baseline(self):
        first=self.initialize();pointer=(self.cache/'baseline.json').read_bytes()
        working=Path(first['working_directory']);path=working/'ConfigDumpInfo.xml'
        path.write_text(path.read_text(encoding='utf-8-sig').replace('configVersion="','configVersion="f',1),encoding='utf-8')
        with self.assertRaises(ValueError):self.initialize(working_directory=str(working))
        self.assertEqual((self.cache/'baseline.json').read_bytes(),pointer)
        self.assertEqual(baseline.read(self.cache)['baseline_id'],first['baseline_id'])

    def test_tampering_and_missing_initialization_have_clear_errors(self):
        with self.assertRaisesRegex(ValueError,'Initialize'):baseline.read(self.cache)
        first=self.initialize();file=next((Path(first['baseline_directory'])/'Catalogs').glob('*.xml'))
        file.write_bytes(file.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'modified'):baseline.read(self.cache)

    def test_implicit_basis_requires_its_working_directory(self):
        result=self.initialize()
        loaded=baseline.run(dict(mode='read',cache_directory=str(self.cache),working_directory=result['working_directory']))
        self.assertEqual(loaded['baseline_id'],result['baseline_id'])
        with self.assertRaisesRegex(ValueError,'working_directory'):
            baseline.run(dict(mode='read',cache_directory=str(self.cache),working_directory=str(self.work/'unrelated')))

    def test_failed_export_and_stale_generation_leave_active_pointer(self):
        self.initialize();pointer=(self.cache/'baseline.json').read_bytes()
        with mock.patch.object(baseline.ibcmd_backend.Compiler,'__enter__',side_effect=ValueError('compiler failed')):
            with self.assertRaisesRegex(ValueError,'compiler failed'):self.initialize()
        with self.assertRaisesRegex(ValueError,'Cache changed'):self.initialize(generation='a'*32)
        self.assertEqual((self.cache/'baseline.json').read_bytes(),pointer)

    def test_unrepresented_native_stream_does_not_publish_a_new_baseline(self):
        first=self.initialize();pointer=(self.cache/'baseline.json').read_bytes()
        working=export.inventory(first['working_directory'])[1]
        with self.assertRaisesRegex(ValueError,'Unmapped nonempty native stream'):
            self.initialize(native_image={self.state['root_id']+'.future':b'unrepresented content'})
        self.assertEqual((self.cache/'baseline.json').read_bytes(),pointer)
        self.assertEqual(export.inventory(first['working_directory'])[1],working)


class PromotionTests(unittest.TestCase):
    setUp=BaselineTests.setUp
    initialize=BaselineTests.initialize
    def prepare_receipt(self,use_git=False,source_branch=None):
        self.first=self.initialize();self.working=Path(self.first['working_directory'])
        self.images={oid:('body '+oid).encode() for oid in self.state['objects']}
        for row in self.state['objects'].values():
            for name in row['externals']:self.images[name]=('stream '+name).encode()
        request=json.loads((self.fixture/'request.json').read_text(encoding='utf-8'))['request']
        objects=repository_cache.inventory(request['context'])[2]
        self.oid=next(oid for oid,row in export.inventory(self.working)[2].items() if row['kind']=='Document')
        docs=copy.deepcopy(objects[self.oid]);self.version='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        docs[0][8]=s.atom(base64.b64encode(uuid.UUID(self.version).bytes_le+bytes(4)).decode())
        refs=docs[0][11]
        for i in range(2,len(refs),2):refs[i]=s.atom(base64.b64encode(uuid.UUID(s.val(refs[i])).bytes_le+bytes(4)).decode())
        file=next((self.working/'Documents').glob('*.xml'))
        file.write_bytes(file.read_bytes().replace(b'<Comment/>',b'<Comment>Submitted</Comment>'))
        self.submitted=export.inventory(self.working)[1]
        self.payload=b'compiled packet'
        req=dict(baseline_update=dict(cache_directory=str(self.cache),baseline_id=self.first['baseline_id'],generation=self.state['generation'],use_git=use_git),
                 repository_version=self.state['repository_version'],directory=str(self.working),target_fingerprint=export.fingerprint(self.submitted),
                 compiler=dict(executable=str(self.exe)))
        if source_branch is not None:req['baseline_update']['source_branch']=source_branch
        with mock.patch.object(repository_cache.Cache,'load',return_value=(copy.deepcopy(self.state),copy.deepcopy(self.images),self.cf)):
            self.receipt=baseline.register(req,{self.oid:(docs,b'submitted body',[])},self.payload)
        self.after=copy.deepcopy(self.state);self.after.update(generation='e'*32,repository_version='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')
        self.after['objects'][self.oid]['local']=self.version
        self.after_image=dict(self.images);self.after_image[self.oid]=b'submitted body'
        self.after_cf=self.cache/'generations'/self.after['generation']/'base.cf';self.after_cf.parent.mkdir();self.after_cf.write_bytes(b'new CF')
        self.promote=dict(self.receipt,generation=self.after['generation'],packet=base64.b64encode(self.payload).decode())

    def advance(self,**extra):
        def execute(compiler,*args):
            shutil.copytree(self.fixture/'baseline',args[3])
            path=Path(args[3])/'ConfigDumpInfo.xml';tree=E.parse(path)
            versions=baseline.expected_versions(self.after)
            for node in tree.getroot().iter(export.D+'Metadata'):
                if node.get('configVersion') is not None:node.set('configVersion',versions[node.get('id')])
            tree.write(path,encoding='utf-8',xml_declaration=True)
        with mock.patch.object(repository_cache.Cache,'load',return_value=(copy.deepcopy(self.after),copy.deepcopy(self.after_image),self.after_cf)),mock.patch.object(baseline.ibcmd_backend.Compiler,'execute',autospec=True,side_effect=execute):
            return baseline.advance(dict(self.promote,**extra))

    def test_promotion_preserves_submitted_xml_and_later_working_edits(self):
        self.prepare_receipt()
        file=next((self.working/'Documents').glob('*.xml'));file.write_bytes(file.read_bytes()+b'<!-- next edit -->')
        working=export.inventory(self.working)[1];result=self.advance()
        self.assertTrue(result['updated']);self.assertNotEqual(result['baseline_id'],self.first['baseline_id'])
        files=export.inventory(result['baseline_directory'])[1]
        self.assertEqual({k:v for k,v in files.items() if k!='ConfigDumpInfo.xml'},{k:v for k,v in self.submitted.items() if k!='ConfigDumpInfo.xml'})
        self.assertEqual(baseline.version_map(files),baseline.expected_versions(self.after))
        self.assertEqual(export.inventory(self.working)[1],working)
        self.assertEqual(self.advance()['baseline_id'],result['baseline_id'])

    def test_git_records_the_confirmed_put_and_retries_do_not_duplicate_it(self):
        if shutil.which('git') is None:self.skipTest('Git is required')
        import xml_git
        self.prepare_receipt(use_git=True);result=self.advance()
        git=xml_git.Git(result['git_directory'])
        self.assertEqual(git.head(),result['repository_commit'])
        self.assertEqual(git.history(self.after)[1],{self.after['repository_version']:result['repository_commit']})
        self.assertEqual(self.advance()['repository_commit'],result['repository_commit'])
        self.assertEqual(git.execute('rev-list','--count',git.source_ref).stdout.strip(),b'1')

    def test_custom_git_branch_survives_receipt_and_baseline_promotion(self):
        if shutil.which('git') is None:self.skipTest('Git is required')
        import xml_git
        self.prepare_receipt(use_git=True,source_branch='refs/heads/storage/incoming')
        receipt=json.loads((self.cache/'pending'/self.promote['receipt_id']/'receipt.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['source_branch'],'storage/incoming')
        result=self.advance();self.assertEqual(result['source_branch'],'storage/incoming')
        git=xml_git.Git(result['git_directory'],'storage/incoming')
        self.assertEqual(git.head(),result['repository_commit'])
        self.assertIsNone(xml_git.Git(result['git_directory']).head())
        self.assertEqual(self.advance()['repository_commit'],result['repository_commit'])

    def test_git_failure_keeps_old_basis_and_can_be_retried(self):
        if shutil.which('git') is None:self.skipTest('Git is required')
        import xml_git
        self.prepare_receipt(use_git=True);pointer=(self.cache/'baseline.json').read_bytes()
        with mock.patch.object(xml_git.Git,'commit',side_effect=ValueError('Git unavailable')):
            with self.assertRaisesRegex(ValueError,'Git unavailable'):self.advance()
        self.assertEqual((self.cache/'baseline.json').read_bytes(),pointer)
        self.assertTrue(self.advance()['updated'])

    def test_interruption_after_git_commit_reuses_it_on_retry(self):
        if shutil.which('git') is None:self.skipTest('Git is required')
        import xml_git
        self.prepare_receipt(use_git=True);pointer=(self.cache/'baseline.json').read_bytes()
        with mock.patch.object(baseline,'publish',side_effect=OSError('pointer write failed')):
            with self.assertRaisesRegex(OSError,'pointer write failed'):self.advance()
        git=xml_git.Git(self.cache/'xml.git');head=git.head()
        self.assertIsNotNone(head);self.assertEqual((self.cache/'baseline.json').read_bytes(),pointer)
        result=self.advance()
        self.assertEqual(result['repository_commit'],head)
        self.assertEqual(git.execute('rev-list','--count',git.source_ref).stdout.strip(),b'1')

    def test_receipt_excludes_removed_objects_and_all_their_streams(self):
        self.prepare_receipt()
        _,_,records,_=export.inventory(self.working)
        record=next(r for r in records.values() if r['kind']=='Constant');removed=record['id']
        (self.working/record['path']).unlink()
        path=self.working/'Configuration.xml';tree=E.parse(path);children=tree.getroot()[0].find(export.Q+'ChildObjects')
        children.remove(next(n for n in children if n.tag==export.Q+'Constant'));tree.write(path,encoding='utf-8')
        self.state['objects'][removed]['externals']={removed+'.0':self.version};self.images[removed+'.0']=b'removed stream'
        req=dict(baseline_update=dict(cache_directory=str(self.cache),baseline_id=self.first['baseline_id'],generation=self.state['generation']),
                 repository_version=self.state['repository_version'],directory=str(self.working),target_fingerprint=export.fingerprint(export.inventory(self.working)[1]),compiler=dict(executable=str(self.exe)))
        with mock.patch.object(repository_cache.Cache,'load',return_value=(copy.deepcopy(self.state),copy.deepcopy(self.images),self.cf)):
            result=baseline.register(req,{},b'deletion packet',{removed})
        receipt=json.loads((self.cache/'pending'/result['receipt_id']/'receipt.json').read_text(encoding='utf-8'))
        self.assertNotIn(removed,receipt['expected_objects']);self.assertNotIn(removed,receipt['expected_entries']);self.assertNotIn(removed+'.0',receipt['expected_entries'])
        self.assertEqual(baseline.read(self.cache)['baseline_id'],self.first['baseline_id'])

    def test_receipt_registers_new_object_identity_and_compiled_module(self):
        self.prepare_receipt();new='cccccccc-cccc-4ccc-8ccc-cccccccccccc'
        records=export.inventory(self.working)[2];source=next(r for r in records.values() if r['kind']=='Catalog')
        text=(self.working/source['path']).read_text(encoding='utf-8-sig').replace(source['id'],new).replace(source['name'],'ReceiptExtra')
        path=self.working/'Catalogs/ReceiptExtra.xml';path.write_text(text,encoding='utf-8')
        root=self.working/'Configuration.xml';tree=E.parse(root);E.SubElement(tree.getroot()[0].find(export.Q+'ChildObjects'),export.Q+'Catalog').text='ReceiptExtra';tree.write(root,encoding='utf-8')
        source_request=json.loads((self.fixture/'request.json').read_text(encoding='utf-8'))['request']
        docs=copy.deepcopy(repository_cache.inventory(source_request['context'])[2][source['id']])
        encoded=base64.b64encode(uuid.UUID(self.version).bytes_le+bytes(4)).decode()
        docs[0][0]=s.atom(6);docs[0][1]=s.atom(new);docs[0][7]=docs[0][8]=s.atom(encoded);docs[0][9]=s.atom('ReceiptExtra',True)
        name=new+'.0';docs[0][11]=[s.atom(1),s.atom(name,True),s.atom(encoded)]
        req=dict(baseline_update=dict(cache_directory=str(self.cache),baseline_id=self.first['baseline_id'],generation=self.state['generation']),
                 repository_version=self.state['repository_version'],directory=str(self.working),target_fingerprint=export.fingerprint(export.inventory(self.working)[1]),compiler=dict(executable=str(self.exe)))
        with mock.patch.object(repository_cache.Cache,'load',return_value=(copy.deepcopy(self.state),copy.deepcopy(self.images),self.cf)):
            result=baseline.register(req,{new:(docs,b'new object',[(name,s.compress(b'new module'))])},b'creation packet')
        receipt=json.loads((self.cache/'pending'/result['receipt_id']/'receipt.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['expected_objects'][new]['local'],self.version)
        self.assertEqual(receipt['expected_objects'][new]['parent_id'],self.state['root_id'])
        self.assertEqual(receipt['expected_entries'][name],repository_cache.digest(b'new module'))
        self.assertEqual(baseline.read(self.cache)['baseline_id'],self.first['baseline_id'])

    def test_unconfirmed_mismatched_or_concurrent_versions_do_not_advance(self):
        self.prepare_receipt();pointer=(self.cache/'baseline.json').read_bytes()
        self.after['repository_version']=self.state['repository_version']
        with self.assertRaisesRegex(ValueError,'not confirmed'):self.advance()
        self.after['repository_version']='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
        self.after_image[self.oid]=b'different server content'
        with self.assertRaisesRegex(ValueError,'differ'):self.advance()
        self.after_image[self.oid]=b'submitted body'
        other=next(oid for oid in self.after['objects'] if oid!=self.oid);self.after['objects'][other]['local']=self.version
        with self.assertRaisesRegex(ValueError,'differ'):self.advance()
        self.assertEqual((self.cache/'baseline.json').read_bytes(),pointer)

    def test_tampered_receipt_packet_failed_export_and_superseded_basis_are_safe(self):
        self.prepare_receipt();pointer=(self.cache/'baseline.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'checksum'):self.advance(receipt_sha256='bad')
        with self.assertRaisesRegex(ValueError,'Packet differs'):self.advance(packet=base64.b64encode(b'other').decode())
        with mock.patch.object(baseline.ibcmd_backend.Compiler,'__enter__',side_effect=ValueError('export failed')):
            with self.assertRaisesRegex(ValueError,'export failed'):self.advance()
        self.assertEqual((self.cache/'baseline.json').read_bytes(),pointer)
        newer=self.initialize()
        with self.assertRaisesRegex(ValueError,'Active baseline changed'):self.advance()
        self.assertEqual(baseline.read(self.cache)['baseline_id'],newer['baseline_id'])


if __name__=='__main__':unittest.main()
