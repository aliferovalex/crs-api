"""One final graph combines retained object changes and recursive removals."""
import base64,copy,shutil,unittest,uuid
from xml.etree import ElementTree as E
import test_configuration_export as export_cases
from unittest.mock import patch
from test_managed_form_creation import store
import configuration_commit as commit
import configuration_batch as batch
import metadata_context
import metadata_identifiers
import xml_namespaces
import native_metadata as s
import object_creation_serializer as c


class ConfigurationCommitTests(unittest.TestCase):
    def setUp(self):
        self.export=export_cases.ConfigurationExportTests();self.export.setUp();self.addCleanup(self.export.doCleanups)
        self.f=self.export.fixture;self.objects=copy.deepcopy(self.export.objects)

    def request(self):
        info=self.export.new/'InformationRegisters/CRSAPI_CollectionRegister.xml'
        top=E.parse(info);children=top.getroot()[0].find(commit.preparation.Q+'ChildObjects')
        removed=self.f['remaining_form_id'];name=s.val(self.objects[removed][0][9])
        children.remove(next(node for node in children if node.tag==commit.preparation.Q+'Form' and node.text==name));top.write(info,encoding='utf-8')
        path=self.export.new/self.export.paths[removed]
        assert self.export.new.resolve() in path.with_suffix('').resolve().parents
        path.unlink();shutil.rmtree(path.with_suffix(''))
        root=self.export.new/'Configuration.xml';root.write_bytes(root.read_bytes().replace(b'Original',b'Combined root change'))
        context=base64.b64encode(s.storage([s.text_bytes(d) for d in self.objects.values()],s.text_bytes([[s.atom(0)]]))).decode()
        r=dict(directory=str(self.export.new),baseline_directory=str(self.export.old),context=context,platform='8.5.1.1529',repository='Synthetic',repository_version=self.f['request']['repository_version'])
        plan,changes=commit.prepare(r);r.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'],snapshots={},originals={})
        for oid in plan['snapshot_ids']:
            m=self.objects[oid][0]
            raw=(self.f['root_before'] if s.val(m[3])==s.ZERO else self.f['owner_before'] if oid==self.f['request']['parent_id'] else 'opaque deleted body').encode('utf-8')
            r['snapshots'][oid]=store(self.objects[oid],raw);r['originals'][oid]=uuid.UUID(s.val(m[7])).bytes_le.hex()+'00000000'
        import native_version_fixture
        r['storage']=native_version_fixture.storage(self.objects)
        return r,plan

    def test_root_and_register_changes_remove_one_form_in_one_final_graph(self):
        r,plan=self.request();result=commit.serialize(r);graph,records=batch.read_packet(result['data'])
        self.assertEqual(len(records),2);self.assertEqual(result['removed_ids'],[self.f['remaining_form_id']])
        self.assertEqual([row['id'] for row in result['descriptions']],result['changed_ids'])
        flags={s.val(graph[4][i]):s.val(graph[4][i+1]) for i in range(1,len(graph[4]),2)}
        self.assertEqual(flags[self.f['remaining_form_id']],'0');self.assertEqual(s.val(graph[10]),'1')
        self.assertEqual(len(result['requested']),len(self.objects)-1)
        for record in records:
            docs=s.Parser(record.metadata.decode('utf-8-sig')).documents()
            self.assertNotIn(self.f['remaining_form_id'],[oid for oid,_ in metadata_context.children(docs[0])])
            self.assertNotIn(self.f['remaining_form_id'],s.inflate(record.body).decode('utf-8-sig'))

    def test_incoming_reference_from_unchanged_form_is_checked_on_final_graph(self):
        oid=self.f['request']['removed_ids'][0];m=self.objects[oid][0];refs=s.metadata_relations(m[14]);refs[self.f['remaining_form_id']]=0
        m[14]=[s.atom(len(refs))]+[s.atom(key) for key in refs]+[s.atom(value) for value in refs.values()]
        r,_=self.request()
        with self.assertRaisesRegex(ValueError,'incoming deletion references'):commit.serialize(r)

    def test_final_graph_can_remove_an_owner_and_all_separately_stored_descendants(self):
        r,_=self.request();root=self.export.new/'Configuration.xml';top=E.parse(root)
        children=top.getroot()[0].find(commit.preparation.Q+'ChildObjects')
        children.remove(next(node for node in children if node.tag==commit.preparation.Q+'InformationRegister'));top.write(root,encoding='utf-8')
        owner=self.export.new/self.export.paths[self.f['request']['parent_id']];directory=owner.with_suffix('')
        assert self.export.new.resolve() in directory.resolve().parents
        owner.unlink();shutil.rmtree(directory)
        plan,_=commit.prepare(r);r.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
        for oid in plan['snapshot_ids']:
            if oid not in r['snapshots']:
                m=self.objects[oid][0];r['snapshots'][oid]=store(self.objects[oid],b'opaque deleted subtree body');r['originals'][oid]=uuid.UUID(s.val(m[7])).bytes_le.hex()+'00000000'
        result=commit.serialize(r);graph,records=batch.read_packet(result['data'])
        self.assertEqual(len(records),1);self.assertEqual(len(result['removed_ids']),4)
        self.assertEqual(len(result['requested']),len(self.objects)-4)
        active={s.val(graph[4][i]):s.val(graph[4][i+1]) for i in range(1,len(graph[4]),2)}
        for oid in result['removed_ids']:self.assertEqual(active[oid],'0')

    def test_source_versions_and_target_changes_after_planning_are_rejected(self):
        r,plan=self.request();bad=copy.deepcopy(r);bad['originals'][plan['snapshot_ids'][-1]]='f'*40
        with self.assertRaisesRegex(ValueError,'Source version'):commit.serialize(bad)
        path=self.export.new/'Configuration.xml';path.write_bytes(path.read_bytes().replace(b'Combined root change',b'Changed again'))
        with self.assertRaisesRegex(ValueError,'directories changed'):commit.serialize(r)

    def add_form_files(self,kind,parent_path,name,oid,interface):
        q=commit.preparation.Q
        directory=self.export.new/parent_path
        path=directory/(name+'.xml');path.parent.mkdir(parents=True,exist_ok=True)
        root=E.Element(q+'MetaDataObject',version='2.21');obj=E.SubElement(root,q+kind,uuid=oid)
        props=E.SubElement(obj,q+'Properties');E.SubElement(props,q+'Name').text=name
        path.write_bytes(E.tostring(root,encoding='utf-8'))
        ext=path.with_suffix('')/'Ext';ext.mkdir(parents=True)
        (ext/'Form.xml').write_text(interface,encoding='utf-8');(ext/'Form').mkdir()
        (ext/'Form/Module.bsl').write_text('// whole new form module',encoding='utf-8')

    def assert_new_form(self,result,oid,parent,position):
        import managed_form_xml as forms
        _,records=batch.read_packet(result['data']);record=next(row for row in records if row.object_id==oid)
        docs=s.Parser(record.metadata.decode('utf-8-sig')).documents()
        self.assertEqual(s.val(docs[0][3]),parent);self.assertEqual(s.val(docs[0][10]),str(position))
        self.assertEqual(len(record.externals),1);self.assertEqual(record.externals[0][0],oid+'.0')
        interface=forms.interface(s.inflate(record.externals[0][1]))
        self.assertEqual(s.val(interface[2]),'// whole new form module')
        owner=next(row for row in records if row.object_id==parent)
        self.assertIn(oid,[key for key,_ in metadata_context.children(s.Parser(owner.metadata.decode('utf-8-sig')).documents()[0])])

    def test_two_common_forms_join_root_change_and_form_deletion(self):
        from test_form_kinds_xml import common_xml
        r,_=self.request();root=self.export.new/'Configuration.xml';top=E.parse(root);q=commit.preparation.Q
        created=['aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee','bbbbbbbb-cccc-4ddd-8eee-ffffffffffff']
        for index,oid in enumerate(created):
            name='BatchForm'+str(index);E.SubElement(top.getroot()[0].find(q+'ChildObjects'),q+'CommonForm').text=name
            self.add_form_files('CommonForm','CommonForms',name,oid,common_xml())
        top.write(root,encoding='utf-8');plan,_=commit.prepare(r)
        r.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
        for oid in plan['snapshot_ids']:
            if oid not in r['snapshots']:
                m=self.objects[oid][0];r['snapshots'][oid]=store(self.objects[oid],b'opaque unchanged body');r['originals'][oid]=uuid.UUID(s.val(m[7])).bytes_le.hex()+'00000000'
        result=commit.serialize(r);self.assertEqual(set(result['new_ids']),set(created))
        parent=next(oid for oid,d in self.objects.items() if s.val(d[0][3])==s.ZERO)
        for index,oid in enumerate(created):self.assert_new_form(result,oid,parent,index)
        self.assertEqual(result['removed_ids'],[self.f['remaining_form_id']])

    def test_new_common_form_requires_complete_interface_file(self):
        from test_form_kinds_xml import common_xml
        r,_=self.request();root=self.export.new/'Configuration.xml';top=E.parse(root);q=commit.preparation.Q
        E.SubElement(top.getroot()[0].find(q+'ChildObjects'),q+'CommonForm').text='MissingInterface';top.write(root,encoding='utf-8')
        self.add_form_files('CommonForm','CommonForms','MissingInterface','aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',common_xml())
        (self.export.new/'CommonForms/MissingInterface/Ext/Form.xml').unlink()
        with self.assertRaisesRegex(ValueError,'Missing or oversized export file'):commit.prepare(r)

    def test_form_replacement_at_another_owner_copies_complete_interface_and_module(self):
        """The UUID changes; source removal and destination creation share a packet."""
        from test_form_kinds_xml import common_xml,native
        import managed_form_xml as forms
        r,_=self.request();q=commit.preparation.Q;removed=self.f['remaining_form_id']
        created='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeef'
        name=s.val(self.objects[removed][0][9]);source=self.export.old/self.export.paths[removed]
        interface=common_xml();module='// complete copied module\nПроцедура Проверка()\nКонецПроцедуры'
        (source.with_suffix('')/'Ext/Form.xml').write_text(interface,encoding='utf-8')
        (source.with_suffix('')/'Ext/Form/Module.bsl').write_text(module,encoding='utf-8')
        destination=self.export.new/'CommonForms'/(name+'.xml');destination.parent.mkdir()
        definition=E.parse(source);definition.getroot()[0].tag=q+'CommonForm';definition.getroot()[0].set('uuid',created)
        definition.getroot()[0].remove(definition.getroot()[0].find(q+'ChildObjects'))
        definition.write(destination,encoding='utf-8');shutil.copytree(source.with_suffix(''),destination.with_suffix(''))
        root=self.export.new/'Configuration.xml';top=E.parse(root)
        E.SubElement(top.getroot()[0].find(q+'ChildObjects'),q+'CommonForm').text=name;top.write(root,encoding='utf-8')
        plan,_=commit.prepare(r)
        self.assertEqual(plan['removed_ids'],[removed]);self.assertEqual(plan['new_ids'],[created])
        r.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
        for oid in plan['snapshot_ids']:
            if oid not in r['snapshots']:
                r['snapshots'][oid]=store(self.objects[oid],b'unchanged opaque body')
                r['originals'][oid]=uuid.UUID(s.val(self.objects[oid][0][7])).bytes_le.hex()+'00000000'
        with patch.object(commit.packets,'assemble',wraps=commit.packets.assemble) as assemble:
            result=commit.serialize(r);self.assertEqual(assemble.call_count,1)
        graph,records=batch.read_packet(result['data']);by_id={row.object_id:row for row in records}
        self.assertNotIn(removed,by_id)
        root_id=next(oid for oid,docs in self.objects.items() if s.val(docs[0][3])==s.ZERO)
        new_metadata=s.Parser(by_id[created].metadata.decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.val(new_metadata[3]),root_id)
        for owner,wanted,unwanted in ((root_id,created,removed),(self.f['request']['parent_id'],None,removed)):
            metadata=s.Parser(by_id[owner].metadata.decode('utf-8-sig')).documents()[0]
            children={oid for oid,_ in metadata_context.children(metadata)}
            self.assertNotIn(unwanted,children)
            if wanted:self.assertIn(wanted,children)
        external=forms.interface(s.inflate(by_id[created].externals[0][1]))
        self.assertEqual(s.val(external[2]).replace('\r\n','\n'),module)
        expected=forms.interface(forms.convert(native('CommonForm'),interface,module_text=module,kind='CommonForm'))
        from test_defined_type_forms import signature
        self.assertEqual(signature(external),signature(expected))
        flags={s.val(graph[4][i]):s.val(graph[4][i+1]) for i in range(1,len(graph[4]),2)}
        self.assertEqual(flags[removed],'0');self.assertEqual(flags[created],'1')

    def test_register_form_creation_is_included_in_the_common_plan(self):
        r,_=self.request();path=self.export.new/'InformationRegisters/CRSAPI_CollectionRegister.xml';top=E.parse(path);q=commit.preparation.Q
        E.SubElement(top.getroot()[0].find(q+'ChildObjects'),q+'Form').text='NewRegisterForm';top.write(path,encoding='utf-8')
        self.add_form_files('Form','InformationRegisters/CRSAPI_CollectionRegister/Forms','NewRegisterForm','aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee','<Form/>')
        plan,_=commit.prepare(r)
        self.assertEqual(plan['creation_plans'][0]['kind'],'InformationRegisterForm')

    def test_two_new_constants_join_changes_and_a_form_deletion(self):
        r,_=self.request();root=self.export.new/'Configuration.xml';top=E.parse(root);q=commit.preparation.Q
        created=['aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee','bbbbbbbb-cccc-4ddd-8eee-ffffffffffff']
        for index,oid in enumerate(created):
            name='BatchConstant'+str(index);E.SubElement(top.getroot()[0].find(q+'ChildObjects'),q+'Constant').text=name
            path=self.export.new/'Constants'/(name+'.xml');path.parent.mkdir(exist_ok=True)
            text=('<MetaDataObject xmlns="%s" xmlns:v8="%s" version="2.21"><Constant uuid="%s"><Properties><Name>%s</Name>'
                  '<Type><v8:Type>xs:string</v8:Type><v8:StringQualifiers><v8:Length>64</v8:Length><v8:AllowedLength>Variable</v8:AllowedLength>'
                  '</v8:StringQualifiers></Type></Properties></Constant></MetaDataObject>')%(xml_namespaces.MD,xml_namespaces.CORE,oid,name)
            path.write_text(text,encoding='utf-8')
        top.write(root,encoding='utf-8');plan,_=commit.prepare(r);r.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
        for oid in plan['snapshot_ids']:
            if oid not in r['snapshots']:
                m=self.objects[oid][0];r['snapshots'][oid]=store(self.objects[oid],b'opaque existing body');r['originals'][oid]=uuid.UUID(s.val(m[7])).bytes_le.hex()+'00000000'
        with patch.object(commit.packets,'assemble',wraps=commit.packets.assemble) as assemble:
            result=commit.serialize(r)
            self.assertEqual(assemble.call_count,1)
        graph,records=batch.read_packet(result['data'])
        self.assertEqual(set(result['new_ids']),set(created));self.assertEqual(len(records),4);self.assertEqual(len(result['changed_ids']),2)
        positions={d['id']:d['pos'] for d in result['descriptions']};self.assertEqual([positions[oid] for oid in created],[0,1])
        self.assertGreater(int(s.val(graph[6][0])),0)
        root_id=next(oid for oid,d in self.objects.items() if s.val(d[0][3])==s.ZERO)
        root_record=next(record for record in records if record.object_id==root_id);metadata=s.Parser(root_record.metadata.decode('utf-8-sig')).documents()[0]
        self.assertEqual([oid for oid,cls in metadata_context.children(metadata) if cls==c.CLASS],created)

    def test_deletion_without_creation_reads_and_repositions_the_retained_form(self):
        owner=self.f['request']['parent_id'];forms=[oid for oid,cls in metadata_context.children(self.objects[owner][0]) if cls==metadata_identifiers.class_id('InformationRegisterForm')]
        removed=min(forms,key=lambda oid:int(s.val(self.objects[oid][0][10])));kept=next(oid for oid in forms if oid!=removed)
        path=self.export.new/self.export.paths[owner];top=E.parse(path);children=top.getroot()[0].find(commit.preparation.Q+'ChildObjects')
        children.remove(next(node for node in children if node.tag==commit.preparation.Q+'Form' and node.text==s.val(self.objects[removed][0][9])));top.write(path,encoding='utf-8')
        file=self.export.new/self.export.paths[removed];directory=file.with_suffix('');assert self.export.new.resolve() in directory.resolve().parents
        file.unlink();shutil.rmtree(directory)
        context=base64.b64encode(s.storage([s.text_bytes(d) for d in self.objects.values()],s.text_bytes([[s.atom(0)]]))).decode()
        r=dict(directory=str(self.export.new),baseline_directory=str(self.export.old),context=context,platform='8.5.1.1529',repository='Synthetic',repository_version=self.f['request']['repository_version'])
        plan,_=commit.prepare(r);self.assertIn(kept,plan['snapshot_ids']);self.assertEqual(plan['new_ids'],[])
        r.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'],snapshots={},originals={})
        for oid in plan['snapshot_ids']:
            raw=self.f['owner_before'].encode('utf-8') if oid==owner else b'opaque untouched form body'
            r['snapshots'][oid]=store(self.objects[oid],raw);r['originals'][oid]=uuid.UUID(s.val(self.objects[oid][0][7])).bytes_le.hex()+'00000000'
        import native_version_fixture
        r['storage']=native_version_fixture.storage(self.objects)
        result=commit.serialize(r);_,records=batch.read_packet(result['data']);record=next(row for row in records if row.object_id==kept)
        self.assertEqual(s.inflate(record.body),b'opaque untouched form body')
        self.assertEqual(s.val(s.Parser(record.metadata.decode('utf-8-sig')).documents()[0][10]),'0')


if __name__=='__main__':unittest.main()
