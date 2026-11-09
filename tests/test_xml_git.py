"""Real Git three-way merges and automatic, version-bound source commits."""
import copy
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
import uuid
from unittest import mock
from xml.etree import ElementTree as E

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import configuration_export as export
import repository_cache
import xml_git

NEW='55555555-5555-4555-8555-555555555555'
NEXT='66666666-6666-4666-8666-666666666666'
REPO='77777777-7777-4777-8777-777777777777'


def comment(directory,folder,value):
    path=next((directory/folder).glob('*.xml'));text=path.read_text(encoding='utf-8-sig')
    text,count=re.subn(r'<Comment(?:\s*/>|>.*?</Comment>)','<Comment>'+value+'</Comment>',text,count=1,flags=re.S)
    assert count==1;path.write_text(text,encoding='utf-8-sig');return path.relative_to(directory).as_posix()


class XmlGitTests(unittest.TestCase):
    def setUp(self):
        if shutil.which('git') is None:self.skipTest('Git is required')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.work=Path(self.temp.name)
        fixture=Path(__file__).with_name('fixtures')/'ibcmd_document'
        request=json.loads((fixture/'request.json').read_text(encoding='utf-8'))['request']
        self.base=self.work/'base';self.local=self.work/'local';self.remote=self.work/'remote'
        for path in [self.base,self.local,self.remote]:shutil.copytree(fixture/'baseline',path)
        root,records,_=repository_cache.inventory(request['context'])
        self.state=dict(generation='f'*32,root_id=root,repository_id=REPO,platform=request['platform'],repository_version=NEW,objects=records)
        self.cf=self.work/'source.cf';self.cf.write_bytes(b'placeholder')
        self.exe=self.work/'compiler.exe';self.exe.write_bytes(b'placeholder')
        self.request=dict(cache_directory=str(self.work/'.crs-cache'),generation=self.state['generation'],directory=str(self.local),baseline_directory=str(self.base),executable=str(self.exe))
        self.update_remote('Remote document',NEW)

    def update_remote(self,text,version):
        comment(self.remote,'Documents',text)
        _,_,objects,_=export.inventory(self.remote)
        oid=next(oid for oid,row in objects.items() if row['kind']=='Document')
        self.state['objects'][oid]['local']=version;self.state['repository_version']=version
        path=self.remote/'ConfigDumpInfo.xml';tree=E.parse(path)
        next(node for node in tree.getroot().iter(export.D+'Metadata') if node.get('id')==oid).set('configVersion',uuid.UUID(version).bytes_le.hex()+'00000000')
        tree.write(path,encoding='utf-8',xml_declaration=True)

    def reconcile(self):
        def execute(compiler,*args):
            self.assertEqual(args[:2],('cf','export'));shutil.copytree(self.remote,Path(args[3]))
            return dict(ok=True)
        with mock.patch.object(repository_cache.Cache,'load',return_value=(copy.deepcopy(self.state),{},self.cf)), \
                mock.patch.object(xml_git.ibcmd_backend.Compiler,'execute',autospec=True,side_effect=execute):
            return xml_git.reconcile(self.request)

    def source_count(self):
        git=xml_git.Git(self.work/'.crs-cache'/'xml.git')
        return int(git.execute('rev-list','--count',git.source_ref).stdout)

    def test_independent_changes_merge_and_input_directories_stay_unchanged(self):
        local_path=comment(self.local,'Catalogs','Local catalog')
        before=(export.inventory(self.base)[1],export.inventory(self.local)[1])
        result=self.reconcile();self.assertTrue(result['merged'],result)
        merged=Path(result['directory'])
        self.assertIn('Local catalog',(merged/local_path).read_text(encoding='utf-8-sig'))
        self.assertIn('Remote document',next((merged/'Documents').glob('*.xml')).read_text(encoding='utf-8-sig'))
        self.assertEqual(before,(export.inventory(self.base)[1],export.inventory(self.local)[1]))
        self.assertEqual(self.source_count(),1)
        self.assertTrue((merged/'.git').is_file())
        self.assertEqual(xml_git.version_map(export.inventory(result['baseline_directory'])[1]),xml_git.expected_versions(self.state))

    def test_repeated_version_reuses_commit_and_does_not_export_again(self):
        first=self.reconcile()
        with mock.patch.object(repository_cache.Cache,'load',return_value=(copy.deepcopy(self.state),{},self.cf)), \
                mock.patch.object(xml_git.ibcmd_backend.Compiler,'execute',side_effect=AssertionError('Unnecessary export')):
            second=xml_git.reconcile(self.request)
        self.assertEqual(first['repository_commit'],second['repository_commit']);self.assertEqual(self.source_count(),1)

    def test_next_received_version_is_a_child_commit(self):
        first=self.reconcile();self.update_remote('Remote document second',NEXT);second=self.reconcile()
        git=xml_git.Git(second['git_directory'])
        self.assertEqual(git.execute('rev-parse',second['repository_commit']+'^').stdout.decode().strip(),first['repository_commit'])
        self.assertEqual(self.source_count(),2)
        self.assertIn(NEXT,git.execute('log','-1','--format=%B',git.source_ref).stdout.decode())

    def test_next_sync_uses_promoted_basis_and_preserves_the_committed_merge(self):
        comment(self.local,'Catalogs','First local catalog edit')
        first=self.reconcile();self.assertTrue(first['merged'])
        merged=Path(first['directory']);promoted=self.work/'promoted'
        # The server receives exactly the merged tree. Promotion changes only
        # its version information; the original user's directory stays separate.
        shutil.copytree(merged,promoted,ignore=shutil.ignore_patterns('.git'))
        _,_,objects,_=export.inventory(promoted)
        oid=next(oid for oid,row in objects.items() if row['kind']=='Catalog')
        self.state['objects'][oid]['local']=NEXT;self.state['repository_version']=NEXT
        path=promoted/'ConfigDumpInfo.xml';tree=E.parse(path)
        next(node for node in tree.getroot().iter(export.D+'Metadata') if node.get('id')==oid).set('configVersion',uuid.UUID(NEXT).bytes_le.hex()+'00000000')
        tree.write(path,encoding='utf-8',xml_declaration=True)
        self.remote=promoted
        self.request.update(directory=str(merged),baseline_directory=str(promoted))
        path=comment(merged,'Catalogs','Second local catalog edit')
        original=export.inventory(merged)[1]
        second=self.reconcile();self.assertTrue(second['merged'],second)
        files=export.inventory(second['directory'])[1]
        self.assertIn(b'Second local catalog edit',files[path])
        document=next(n for n in files if n.startswith('Documents/') and n.count('/')==1)
        self.assertIn(b'Remote document',files[document])
        self.assertEqual(export.inventory(merged)[1],original)
        self.assertEqual(self.source_count(),2)
        self.assertIn('First local catalog edit',next((self.local/'Catalogs').glob('*.xml')).read_text(encoding='utf-8-sig'))

    def test_conflict_records_incoming_version_but_never_changes_local_files(self):
        path=comment(self.local,'Documents','Conflicting local document');before=export.inventory(self.local)[1]
        result=self.reconcile();self.assertFalse(result['merged'])
        self.assertIn(path,[entry['path'] for entry in result['conflicts']])
        self.assertEqual(export.inventory(self.local)[1],before);self.assertEqual(self.source_count(),1)
        self.assertTrue(Path(result['report_file']).is_file());self.assertNotIn('work_branch',result)

    def test_git_plumbing_preserves_unicode_paths_spaces_and_binary_bytes(self):
        git=xml_git.Git(self.work/'standalone.git');git.initialize()
        files={'Каталог с пробелом/Модуль.bsl':'Процедура Тест()\r\nКонецПроцедуры\r\n'.encode(),'binary.bin':bytes(range(256))}
        commit=git.commit(files,'test fixture')
        self.assertEqual(git.files(commit),files)

    def test_foreign_git_history_cannot_be_reused(self):
        self.reconcile();self.state['repository_id']=str(uuid.uuid4())
        with self.assertRaisesRegex(ValueError,'foreign'):self.reconcile()

    def test_wrong_export_versions_do_not_advance_source_branch(self):
        self.state['objects'][next(iter(self.state['objects']))]['local']=str(uuid.uuid4())
        with self.assertRaisesRegex(ValueError,'Exported XML versions'):self.reconcile()
        self.assertIsNone(xml_git.Git(self.work/'.crs-cache'/'xml.git').head())

    def test_cache_generation_change_is_rejected_before_git_creation(self):
        self.request['generation']='0'*32
        with self.assertRaisesRegex(ValueError,'Cache changed'):self.reconcile()
        self.assertFalse((self.work/'.crs-cache'/'xml.git').exists())

    def test_git_control_files_are_not_part_of_configuration_inventory(self):
        baseline=export.inventory(self.base)[1]
        (self.base/'.git').mkdir();(self.base/'.git'/'config').write_text('not XML')
        (self.base/'.gitignore').write_text('.crs-cache/')
        (self.base/'.crs-cache').mkdir();(self.base/'.crs-cache'/'blob.cf').write_bytes(b'opaque')
        self.assertEqual(export.inventory(self.base)[1],baseline)

    def remove_remote_constant(self):
        _,_,objects,_=export.inventory(self.remote)
        oid=next(oid for oid,row in objects.items() if row['kind']=='Constant');record=objects[oid]
        (self.remote/record['path']).unlink();self.state['objects'].pop(oid)
        path=self.remote/'Configuration.xml';tree=E.parse(path);children=tree.getroot()[0].find(export.Q+'ChildObjects')
        children.remove(next(node for node in children if node.tag==export.Q+'Constant' and node.text==record['name']))
        tree.write(path,encoding='utf-8',xml_declaration=True)
        root=self.state['root_id'];self.state['objects'][root]['local']=NEXT
        path=self.remote/'ConfigDumpInfo.xml';tree=E.parse(path)
        for parent in tree.getroot().iter():
            for node in list(parent):
                if node.tag==export.D+'Metadata' and node.get('id')==oid:parent.remove(node)
                elif node.tag==export.D+'Metadata' and node.get('id')==root:node.set('configVersion',uuid.UUID(NEXT).bytes_le.hex()+'00000000')
        tree.write(path,encoding='utf-8',xml_declaration=True)
        return record['path']

    def test_incoming_deletion_and_independent_local_edit_merge(self):
        comment(self.local,'Catalogs','Kept local edit');removed=self.remove_remote_constant()
        result=self.reconcile();self.assertTrue(result['merged'],result)
        self.assertFalse((Path(result['directory'])/removed).exists())
        self.assertIn('Kept local edit',next((Path(result['directory'])/'Catalogs').glob('*.xml')).read_text(encoding='utf-8-sig'))

    def test_delete_modify_conflict_keeps_original_file(self):
        comment(self.local,'Constants','Locally changed constant');removed=self.remove_remote_constant()
        before=(self.local/removed).read_bytes();result=self.reconcile()
        self.assertFalse(result['merged']);self.assertIn(removed,[row['path'] for row in result['conflicts']])
        self.assertEqual((self.local/removed).read_bytes(),before)

    def test_unchanged_form_stream_keeps_native_helper_ids_when_description_changes(self):
        oid='88888888-8888-4888-8888-888888888888'
        for directory in [self.base,self.remote]:
            owner=next((directory/'Catalogs').glob('*.xml'));tree=E.parse(owner)
            E.SubElement(tree.getroot()[0].find(export.Q+'ChildObjects'),export.Q+'Form').text='Main'
            tree.write(owner,encoding='utf-8',xml_declaration=True)
            path=owner.with_suffix('')/'Forms'/'Main.xml';path.parent.mkdir(parents=True)
            text='<MetaDataObject xmlns="'+export.Q[1:-1]+'"><Form uuid="'+oid+'"><Properties><Name>Main</Name><Comment/></Properties></Form></MetaDataObject>'
            path.write_text(text,encoding='utf-8')
            interface=path.with_suffix('')/'Ext'/'Form.xml';interface.parent.mkdir(parents=True)
            interface.write_text('<Form xmlns="http://v8.1c.ru/8.3/xcf/logform"><ChildItems><ContextMenu name="Menu" id="24"/></ChildItems></Form>',encoding='utf-8')
            dump=directory/'ConfigDumpInfo.xml';tree=E.parse(dump);parent=tree.getroot().find(export.D+'ConfigVersions')
            for key in [oid,oid+'.0']:E.SubElement(parent,export.D+'Metadata',id=key,configVersion=uuid.UUID(NEW).bytes_le.hex()+'00000000')
            tree.write(dump,encoding='utf-8',xml_declaration=True)
        interface=next(self.remote.glob('Catalogs/*/Forms/Main/Ext/Form.xml'))
        interface.write_text(interface.read_text().replace('id="24"','id="23"'),encoding='utf-8')
        definition=interface.parent.parent.with_suffix('.xml')
        definition.write_text(definition.read_text().replace('<Comment/>','<Comment>Remote description</Comment>'),encoding='utf-8')
        dump=self.remote/'ConfigDumpInfo.xml';tree=E.parse(dump)
        next(node for node in tree.getroot().iter(export.D+'Metadata') if node.get('id')==oid).set('configVersion',uuid.UUID(NEXT).bytes_le.hex()+'00000000')
        tree.write(dump,encoding='utf-8',xml_declaration=True)
        files=xml_git.retain_unchanged(self.base,self.remote)
        self.assertIn(b'id="24"',files[interface.relative_to(self.remote).as_posix()])
        self.assertIn(b'Remote description',files[definition.relative_to(self.remote).as_posix()])

    def test_custom_source_branch_is_used_for_sync_and_history(self):
        self.request['source_branch']='storage/incoming'
        result=self.reconcile()
        self.assertEqual(result['source_branch'],'storage/incoming')
        git=xml_git.Git(result['git_directory'],'refs/heads/storage/incoming')
        self.assertEqual(git.head(),result['repository_commit'])
        self.assertEqual(git.execute('symbolic-ref','HEAD').stdout.strip(),b'refs/heads/storage/incoming')
        self.assertIsNone(xml_git.Git(result['git_directory']).head())
        second=self.reconcile();self.assertEqual(second['repository_commit'],result['repository_commit'])
        self.update_remote('Remote next custom branch',NEXT);third=self.reconcile()
        self.assertEqual(git.execute('rev-parse',third['repository_commit']+'^').stdout.decode().strip(),result['repository_commit'])

    def test_invalid_source_branch_is_rejected_before_git_directory_creation(self):
        for branch in ['',None,[],{},'-wrong','refs/tags/repository','refs/heads/refs/heads/nested','refs/heads/refs/tags/nested','a..b','a b','a@{b','codex','codex/crs-work','codex/crs-work/source']:
            with self.subTest(branch=branch),self.assertRaisesRegex(ValueError,'source_branch'):
                xml_git.Git(self.work/'invalid.git',branch)
        self.assertFalse((self.work/'invalid.git').exists())

    def test_root_feature_stream_is_not_replaced_by_the_old_root_files(self):
        _,_,records,_=export.inventory(self.base)
        root=next(row for row in records.values() if row['kind']=='Configuration')
        xr='{http://v8.1c.ru/8.3/xcf/readable}'
        feature=next(node.findtext(xr+'ObjectId') for node in root['node'].iter(xr+'ContainedObject')
                     if node.findtext(xr+'ClassId')=='9cd510cd-abfc-11d4-9434-004095e12fc7')
        self.assertNotEqual(feature,root['id'])
        path=self.remote/'Ext/SessionModule.bsl';path.parent.mkdir(exist_ok=True);path.write_bytes(b'// remote session module')
        dump=self.remote/'ConfigDumpInfo.xml';tree=E.parse(dump)
        E.SubElement(tree.getroot().find(export.D+'ConfigVersions'),export.D+'Metadata',
                     id=feature+'.7',configVersion=uuid.UUID(NEW).bytes_le.hex()+'00000000')
        tree.write(dump,encoding='utf-8',xml_declaration=True)
        files=xml_git.retain_unchanged(self.base,self.remote)
        self.assertEqual(files['Ext/SessionModule.bsl'],b'// remote session module')
        # An unchanged body must not resurrect a remotely deleted companion.
        (self.base/'Ext').mkdir(exist_ok=True)
        shutil.copyfile(path,self.base/'Ext/SessionModule.bsl')
        shutil.copyfile(dump,self.base/'ConfigDumpInfo.xml')
        path.unlink();tree=E.parse(dump)
        parent=tree.getroot().find(export.D+'ConfigVersions')
        parent.remove(next(node for node in parent if node.get('id')==feature+'.7'))
        tree.write(dump,encoding='utf-8',xml_declaration=True)
        self.assertNotIn('Ext/SessionModule.bsl',xml_git.retain_unchanged(self.base,self.remote))

    def test_interruption_after_source_commit_is_recoverable_without_a_duplicate(self):
        with mock.patch.object(xml_git.Git,'merge',side_effect=RuntimeError('Interrupted')):
            with self.assertRaises(RuntimeError):self.reconcile()
        self.assertEqual(self.source_count(),1)
        result=self.reconcile();self.assertTrue(result['merged']);self.assertEqual(self.source_count(),1)

    def test_concurrent_edit_of_input_blocks_preparation_without_overwriting_it(self):
        original=xml_git.Git.merge
        def merge(git,*args):
            result=original(git,*args);comment(self.local,'Catalogs','New edit during synchronization');return result
        with mock.patch.object(xml_git.Git,'merge',autospec=True,side_effect=merge):result=self.reconcile()
        self.assertFalse(result['merged']);self.assertIn('Input XML changed',result['conflicts'][0]['reason'])
        self.assertIn('New edit during synchronization',next((self.local/'Catalogs').glob('*.xml')).read_text(encoding='utf-8-sig'))


if __name__=='__main__':unittest.main()
