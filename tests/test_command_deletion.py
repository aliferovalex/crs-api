"""Whole-export command deletion also removes its companion module file."""
import base64,copy,shutil,sys,tempfile,unittest,uuid
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import configuration_export as export
import metadata_identifiers as ids
import native_metadata as s
import test_object_change_serializer as snapshots
import test_object_xml_profiles as fixtures

CID='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';Q=export.Q


class CommandDeletionTests(unittest.TestCase):
    def case(self,kind,owner_modules=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);base=Path(temp.name);old=base/'old';old.mkdir()
        top=E.fromstring(fixtures.xml(kind));command=E.SubElement(top[0].find(Q+'ChildObjects'),Q+'Command',uuid=CID)
        E.SubElement(E.SubElement(command,Q+'Properties'),Q+'Name').text='Run'
        _,docs,_=snapshots.fixture(kind,E.tostring(top,encoding='unicode'));m=docs[0];oid=s.val(m[1]);parent=s.val(m[3]);name=s.val(m[9])
        versions={CID+'.2':str(uuid.uuid4())}
        if owner_modules:
            for suffix in export.profiles.module_files(kind).values():versions[oid+suffix]=str(uuid.uuid4())
        m[11]=[s.atom(len(versions))]
        for stream_name,version in versions.items():m[11].extend((s.atom(stream_name,True),s.atom(version)))
        root=copy.deepcopy(docs);r=root[0];r[1]=s.atom(parent);r[2]=s.atom(ids.class_id('Configuration'));r[3]=s.atom(s.ZERO);r[9]=s.atom('Root',True)
        r[11]=[s.atom(0)];r[12]=[s.atom(1),[s.atom(ids.class_id(kind)),s.atom(1),s.atom(oid)]];r[13]=[s.atom(0)]
        context=base64.b64encode(s.storage([s.text_bytes(root),s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode()
        rootxml=E.Element(Q+'MetaDataObject',version='2.21');node=E.SubElement(rootxml,Q+'Configuration',uuid=parent)
        E.SubElement(E.SubElement(node,Q+'Properties'),Q+'Name').text='Root';E.SubElement(E.SubElement(node,Q+'ChildObjects'),Q+kind).text=name
        (old/'Configuration.xml').write_bytes(E.tostring(rootxml,encoding='utf-8'))
        path=Path(export.folder(kind))/(name+'.xml');file=old/path;file.parent.mkdir();file.write_bytes(E.tostring(top,encoding='utf-8'))
        module=path.with_suffix('')/'Commands/Run/Ext/CommandModule.bsl';(old/module).parent.mkdir(parents=True);(old/module).write_text('// module',encoding='utf-8')
        if owner_modules:
            for name in export.profiles.module_files(kind):
                own=old/path.with_suffix('')/'Ext'/(name+'.bsl');own.parent.mkdir(parents=True,exist_ok=True);own.write_text('// '+name,encoding='utf-8')
        info=E.Element(export.D+'ConfigDumpInfo',format='Hierarchical');versions=E.SubElement(info,export.D+'ConfigVersions')
        for metadata in (r,m):E.SubElement(versions,export.D+'Metadata',id=s.val(metadata[1]),configVersion=uuid.UUID(s.val(metadata[8])).bytes_le.hex()+'00000000')
        for index in range(1,len(m[11]),2):E.SubElement(versions,export.D+'Metadata',id=s.val(m[11][index]),configVersion=uuid.UUID(s.val(m[11][index+1])).bytes_le.hex()+'00000000')
        (old/'ConfigDumpInfo.xml').write_bytes(E.tostring(info,encoding='utf-8'));new=base/'new';shutil.copytree(old,new)
        return dict(directory=str(new),baseline_directory=str(old),context=context),new/path,new/module,oid

    def test_missing_module_clears_its_retained_command_or_disappears_with_it(self):
        for kind in ('DataProcessor','Report'):
            with self.subTest(kind=kind):
                request,file,module,oid=self.case(kind);module.unlink()
                plan=export.plan(request);self.assertEqual(plan['operations'][0]['removed_inline_modules'],[CID])
                tree=E.parse(file);children=tree.getroot()[0].find(Q+'ChildObjects');children.remove(children.find(Q+'Command'));tree.write(file,encoding='utf-8')
                plan=export.plan(request);self.assertEqual(plan['removed_ids'],[])
                self.assertNotIn('removed_inline_modules',plan['operations'][0])
                self.assertEqual([(op['object_id'],op['operation']) for op in plan['operations']],[(oid,'Изменение')])

    def test_unrelated_missing_file_is_not_treated_as_command_deletion(self):
        request,file,module,_=self.case('DataProcessor');old=Path(request['baseline_directory'])
        stray=module.with_name('Unknown.bsl');relative=stray.relative_to(Path(request['directory']));(old/relative).write_text('// unknown',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Unsupported changed'):export.plan(request)

    def test_whole_commit_propagates_module_removals_even_when_owner_xml_is_unchanged(self):
        import configuration_commit as commit
        import configuration_batch as batch
        import metadata_context
        import metadata_object_xml
        from test_managed_form_creation import store
        for own in (False,True):
            with self.subTest(owner_module=own):
                request,file,command,oid=self.case('DataProcessor',owner_modules=own)
                path=file.with_suffix('')/'Ext/ObjectModule.bsl' if own else command;path.unlink()
                plan,changes=commit.prepare(dict(request,platform='8.5.1.1529'));key='removed_modules' if own else 'removed_inline_modules'
                self.assertEqual(changes[0][key],['ObjectModule'] if own else [CID])
                docs=metadata_context.context_objects(request['context'])[oid];original=metadata_context.context_objects(request['context'])[oid][0]
                before=(Path(request['baseline_directory'])/file.relative_to(Path(request['directory']))).read_text(encoding='utf-8')
                body=metadata_object_xml.create(before,'8.5.1.1529','DataProcessor')[2]
                request.update(platform='8.5.1.1529',repository='Synthetic',repository_version=str(uuid.uuid4()),snapshots={oid:store(docs,body)},originals={oid:uuid.UUID(s.val(docs[0][7])).bytes_le.hex()+'00000000'},target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
                result=commit.serialize(request);_,records=batch.read_packet(result['data']);record=next(row for row in records if row.object_id==oid);updated=s.Parser(record.metadata.decode('utf-8-sig')).documents()[0]
                names={s.val(name) for name in updated[11][1::2]};removed=oid+'.0' if own else CID+'.2'
                self.assertNotIn(removed,names);self.assertEqual(names,{s.val(name) for name in original[11][1::2]}-{removed})
                self.assertEqual(s.inflate(record.body),body)

    def test_command_module_renamed_with_its_command_is_replaced_without_removal(self):
        request,file,module,_=self.case('DataProcessor');tree=E.parse(file);tree.find('.//'+Q+'Command/'+Q+'Properties/'+Q+'Name').text='Renamed';tree.write(file,encoding='utf-8')
        destination=file.with_suffix('')/'Commands/Renamed/Ext/CommandModule.bsl';destination.parent.mkdir(parents=True);module.replace(destination)
        plan=export.plan(request);self.assertNotIn('removed_inline_modules',plan['operations'][0])


if __name__=='__main__':unittest.main()
