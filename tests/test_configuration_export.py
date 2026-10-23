"""Whole-directory planning includes streams and binds the source to the server."""
import json,shutil,sys,tempfile,unittest,uuid
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('configuration_export.py')).parent))
import configuration_export as export
import metadata_context
import native_metadata as s
import metadata_identifiers as ids


class ConfigurationExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.dir=Path(self.temp.name)
        self.old=self.dir/'old';self.new=self.dir/'new';self.old.mkdir()
        fixture=json.loads(Path(__file__).with_name('fixtures').joinpath('native_register_collections_851.json').read_text(encoding='utf-8'))
        self.context=fixture['request']['context'];self.objects=metadata_context.context_objects(self.context);self.fixture=fixture;self.paths={}
        root_id=next(oid for oid,d in self.objects.items() if s.val(d[0][3])==s.ZERO)
        def write(oid,path):
            m=self.objects[oid][0];kind=ids.class_labels()[s.val(m[2])];tag='Form' if kind.endswith('Form') else kind
            doc=E.Element(export.Q+'MetaDataObject',version='2.21');obj=E.SubElement(doc,export.Q+tag,uuid=oid);props=E.SubElement(obj,export.Q+'Properties')
            E.SubElement(props,export.Q+'Name').text=s.val(m[9]);E.SubElement(props,export.Q+'Comment').text='Original'
            if oid==fixture['request']['parent_id']:
                import managed_form_profiles,metadata_common_xml
                props.clear()
                body=s.Parser(fixture['owner_before']).documents()[0]
                metadata_common_xml.write(props,managed_form_profiles.owner_common(body,kind))
            children=E.SubElement(obj,export.Q+'ChildObjects')
            for child,cls in metadata_context.children(m):
                label=ids.class_labels()[cls];ct='Form' if label.endswith('Form') else label
                name=s.val(self.objects[child][0][9]);E.SubElement(children,export.Q+ct).text=name
                prefix=Path('') if oid==root_id else path.with_suffix('')
                write(child,prefix/export.folder(ct)/(name+'.xml'))
            file=self.old/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(E.tostring(doc,encoding='utf-8'));self.paths[oid]=path
            if tag=='Form':
                companion=file.with_suffix('')/'Ext';companion.mkdir(parents=True);(companion/'Form.xml').write_text('<Form/>',encoding='utf-8')
                (companion/'Form').mkdir();(companion/'Form/Module.bsl').write_text('// original',encoding='utf-8')
            if tag=='Template':
                companion=file.with_suffix('')/'Ext';companion.mkdir(parents=True);(companion/'Template.bin').write_bytes(b'original')
        write(root_id,Path('Configuration.xml'))
        info=E.Element(export.D+'ConfigDumpInfo',format='Hierarchical',version='2.21');versions=E.SubElement(info,export.D+'ConfigVersions')
        for oid,d in self.objects.items():
            m=d[0];E.SubElement(versions,export.D+'Metadata',id=oid,configVersion=uuid.UUID(s.val(m[8])).bytes_le.hex()+'00000000')
            for i in range(1,len(m[11]),2):E.SubElement(versions,export.D+'Metadata',id=s.val(m[11][i]),configVersion=uuid.UUID(s.val(m[11][i+1])).bytes_le.hex()+'00000000')
        (self.old/'ConfigDumpInfo.xml').write_bytes(E.tostring(info,encoding='utf-8'));shutil.copytree(self.old,self.new)

    def plan(self):return export.plan(dict(directory=str(self.new),baseline_directory=str(self.old),context=self.context))

    def test_unchanged_export_skips_unsupported_but_version_verified_classes(self):
        result=self.plan();self.assertEqual(result['operations'],[]);self.assertEqual(result['unchanged_count'],len(self.objects))

    def test_xml_and_module_changes_select_their_owners_despite_stale_dumpinfo(self):
        owner=self.fixture['request']['parent_id'];form=self.fixture['remaining_form_id']
        path=self.new/self.paths[owner];top=E.parse(path)
        top.getroot()[0].find(export.Q+'Properties/'+export.Q+'Comment').text='Changed'
        top.write(path,encoding='utf-8')
        module=(self.new/self.paths[form]).with_suffix('')/'Ext/Form/Module.bsl';module.write_text('// changed',encoding='utf-8')
        result=self.plan();self.assertEqual({v['object_id'] for v in result['operations']},{owner,form})
        self.assertEqual(len(result['xml_paths']),2);self.assertNotEqual(result['target_fingerprint'],result['baseline_fingerprint'])

    def test_binary_template_content_is_attributed_to_the_template(self):
        oid=self.fixture['template_id'];path=(self.new/self.paths[oid]).with_suffix('')/'Ext/Template.bin';path.write_bytes(bytes(range(256)))
        result=self.plan();self.assertEqual(len(result['operations']),1)
        self.assertEqual(result['operations'][0]['object_id'],oid)
        self.assertEqual(result['operations'][0]['changed_files'],[path.relative_to(self.new).as_posix()])

    def test_creation_is_reported_alongside_the_changed_root(self):
        oid='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';path=self.new/'Constants/NewConstant.xml';path.parent.mkdir()
        top=E.Element(export.Q+'MetaDataObject',version='2.21');obj=E.SubElement(top,export.Q+'Constant',uuid=oid);props=E.SubElement(obj,export.Q+'Properties')
        E.SubElement(props,export.Q+'Name').text='NewConstant';path.write_bytes(E.tostring(top,encoding='utf-8'))
        root=self.new/'Configuration.xml';doc=E.parse(root);E.SubElement(doc.getroot()[0].find(export.Q+'ChildObjects'),export.Q+'Constant').text='NewConstant';doc.write(root,encoding='utf-8')
        result=self.plan();self.assertEqual(result['new_ids'],[oid]);self.assertEqual(len(result['operations']),2)
        self.assertEqual(next(op for op in result['operations'] if op['object_id']==oid)['operation'],'Создание')

    def test_deleted_form_requires_consistent_owner_and_has_an_explicit_plan_entry(self):
        oid=self.fixture['remaining_form_id'];path=self.new/self.paths[oid]
        assert self.new.resolve() in path.with_suffix('').resolve().parents
        path.unlink();shutil.rmtree(path.with_suffix(''))
        with self.assertRaisesRegex(ValueError,'Missing or inconsistent'):self.plan()
        owner=self.new/self.paths[self.fixture['request']['parent_id']];top=E.parse(owner);children=top.getroot()[0].find(export.Q+'ChildObjects')
        children.remove(next(node for node in children if node.tag==export.Q+'Form' and node.text==s.val(self.objects[oid][0][9])))
        top.write(owner,encoding='utf-8');result=self.plan();self.assertEqual(result['removed_ids'],[oid])
        self.assertIn('Удаление',[op['operation'] for op in result['operations']])

    def test_stale_baseline_and_unknown_changed_companions_are_rejected(self):
        info=self.old/'ConfigDumpInfo.xml';saved=info.read_bytes();top=E.parse(info);node=top.getroot().find('.//'+export.D+'Metadata');node.set('configVersion','f'*40);top.write(info)
        with self.assertRaisesRegex(ValueError,'versions differ'):self.plan()
        info.write_bytes(saved);owner=self.new/self.paths[self.fixture['request']['parent_id']];ext=owner.with_suffix('')/'Ext';ext.mkdir(exist_ok=True)
        (ext/'Unsupported.xml').write_text('<Unsupported/>',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Unsupported changed'):self.plan()

    def test_incomplete_source_or_duplicate_uuid_is_rejected(self):
        form=self.old/self.paths[self.fixture['remaining_form_id']];form.unlink()
        with self.assertRaisesRegex(ValueError,'Missing or inconsistent'):self.plan()
        form.write_bytes((self.new/self.paths[self.fixture['remaining_form_id']]).read_bytes());duplicate=self.new/'Duplicate.xml';duplicate.write_bytes(form.read_bytes())
        with self.assertRaisesRegex(ValueError,'Duplicate export'):self.plan()

    def test_missing_form_contents_in_both_folders_cannot_look_unchanged(self):
        oid=self.fixture['remaining_form_id']
        for directory in (self.old,self.new):((directory/self.paths[oid]).with_suffix('')/'Ext/Form.xml').unlink()
        with self.assertRaisesRegex(ValueError,'missing Form.xml'):self.plan()

    def rename(self,oid,name):
        path=self.new/self.paths[oid];top=E.parse(path);old=top.getroot()[0].findtext(export.Q+'Properties/'+export.Q+'Name')
        top.getroot()[0].find(export.Q+'Properties/'+export.Q+'Name').text=name
        parent=s.val(self.objects[oid][0][3]);owner=E.parse(self.new/self.paths[parent]);tag=top.getroot()[0].tag
        next(node for node in owner.getroot()[0].find(export.Q+'ChildObjects') if node.tag==tag and node.text==old).text=name
        owner.write(self.new/self.paths[parent],encoding='utf-8')
        target=path.with_name(name+'.xml');top.write(target,encoding='utf-8');path.unlink()
        directory=path.with_suffix('')
        if directory.exists():
            assert self.new.resolve() in directory.resolve().parents
            directory.rename(target.with_suffix(''))
        return target

    def test_owner_rename_relocates_unchanged_children_without_spurious_operations(self):
        oid=self.fixture['request']['parent_id'];target=self.rename(oid,'RenamedRegister')
        result=self.plan();self.assertEqual(result['removed_ids'],[]);self.assertEqual(result['new_ids'],[])
        root=next(key for key,docs in self.objects.items() if s.val(docs[0][3])==s.ZERO)
        self.assertEqual({op['object_id'] for op in result['operations']},{root,oid})
        self.assertEqual(next(op for op in result['operations'] if op['object_id']==oid)['changed_files'],[target.relative_to(self.new).as_posix()])
        self.assertEqual(result['unchanged_count'],len(self.objects)-2)

    def test_form_rename_keeps_its_module_and_interface_as_unchanged_companions(self):
        oid=self.fixture['remaining_form_id'];target=self.rename(oid,'RenamedForm');result=self.plan()
        operation=next(op for op in result['operations'] if op['object_id']==oid)
        self.assertEqual(operation['changed_files'],[target.relative_to(self.new).as_posix()])
        self.assertNotIn('clear_module_text',operation)
        self.assertNotIn('removed_modules',operation)
        module=target.with_suffix('')/'Ext/Form/Module.bsl';module.write_text('// changed after rename',encoding='utf-8')
        operation=next(op for op in self.plan()['operations'] if op['object_id']==oid)
        self.assertIn(module.relative_to(self.new).as_posix(),operation['changed_files'])

    def test_complete_plan_supplies_only_changed_owner_module_files(self):
        import configuration_commit as commit
        import object_xml_profiles as profiles
        oid=self.fixture['request']['parent_id'];record=export.inventory(self.old)[2][oid]
        kind=export.runtime_kind(record,export.inventory(self.old)[2]);name=next(iter(profiles.module_files(kind)))
        relative=self.paths[oid].with_suffix('')/'Ext'/(name+'.bsl')
        for directory in (self.old,self.new):
            file=directory/relative;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('',encoding='utf-8')
        owner=self.new/self.paths[oid];top=E.parse(owner)
        top.getroot()[0].find(export.Q+'Properties/'+export.Q+'Comment').text='Changed comment'
        top.write(owner,encoding='utf-8')
        request=dict(directory=str(self.new),baseline_directory=str(self.old),context=self.context,platform='8.5.1.1529')
        _,changes=commit.prepare(request)
        self.assertEqual(len(changes),1);self.assertEqual(changes[0]['modules'],{})
        (self.new/relative).write_text('// changed module',encoding='utf-8')
        _,changes=commit.prepare(request)
        self.assertEqual(changes[0]['modules'],{name:'// changed module'})


if __name__=='__main__':unittest.main()
