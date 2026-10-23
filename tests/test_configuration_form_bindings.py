"""A single full-export packet binds forms to final owner modes and fields."""
import base64,copy,hashlib,shutil,unittest,uuid
from xml.etree import ElementTree as E
import test_configuration_export as exports
from test_managed_form_creation import store
import configuration_commit as commit,configuration_batch as batch
import metadata_context
import metadata_identifiers
import xml_namespaces
import native_metadata as s
import managed_form_operations as forms,managed_form_xml as interfaces
import managed_form_profiles as profiles


class ConfigurationFormBindingsTests(unittest.TestCase):
    def setUp(self):
        self.export=exports.ConfigurationExportTests();self.export.setUp();self.addCleanup(self.export.doCleanups)
        self.fixture=self.export.fixture;self.objects=copy.deepcopy(self.export.objects)
        self.owner_id=self.fixture['request']['parent_id'];self.q=commit.preparation.Q
        self.owner=s.Parser(self.fixture['owner_before']).documents()[0]
        self.owner[1][23]=s.atom(0);self.owner[7][2][0][1][19]=[s.atom('U',True)]
        self.owner_name=s.val(self.objects[self.owner_id][0][9])
        self.bodies={};self.externals={};self.form_ids=[]
        root=E.fromstring(self.fixture['request']['object_xml']);children=root[0].find(self.q+'ChildObjects')
        for child in list(children):
            if child.tag in (self.q+'Form',self.q+'Template'):children.remove(child)
        root[0].find(self.q+'Properties/'+self.q+'Comment').text=s.val(profiles.owner_common(self.owner,'InformationRegister')[4])
        for oid,cls in metadata_context.children(self.objects[self.owner_id][0]):
            kind='Form' if cls==metadata_identifiers.class_id('InformationRegisterForm') else 'Template'
            E.SubElement(children,self.q+kind).text=s.val(self.objects[oid][0][9])
        (self.export.old/self.export.paths[self.owner_id]).write_bytes(E.tostring(root,encoding='utf-8'))
        for oid,docs in self.objects.items():
            kind=metadata_identifiers.class_labels()[s.val(docs[0][2])]
            if oid==self.owner_id:self.bodies[oid]=s.native_body_bytes([self.owner])
            elif kind=='Configuration':self.bodies[oid]=self.fixture['root_before'].encode('utf-8')
            elif kind=='InformationRegisterForm':
                path=self.export.old/self.export.paths[oid];xml=self.interface(('Flag',))
                definition=E.parse(path);definition.getroot()[0].remove(definition.getroot()[0].find(self.q+'ChildObjects'))
                definition.write(path,encoding='utf-8')
                _,body,external=forms.create_native('InformationRegister',s.val(docs[0][9]),'8.5.1.1529',self.owner,
                                                   definition_xml=path.read_text(encoding='utf-8'),interface_xml=xml,module_text='// source')
                self.bodies[oid]=body;self.externals[oid+'.0']=s.compress(external);self.form_ids.append(oid)
                path.with_suffix('').joinpath('Ext/Form.xml').write_text(xml,encoding='utf-8')
                path.with_suffix('').joinpath('Ext/Form/Module.bsl').write_text('// source',encoding='utf-8')
            elif kind=='Template':self.bodies[oid]=s.native_body_bytes([[s.atom(1),[s.atom(2),s.atom(1),s.atom(0)],s.atom(0)]])
            else:self.bodies[oid]=b'opaque unchanged object'
            for name in docs[0][11][1::2]:self.externals.setdefault(s.val(name),s.compress(b'opaque unchanged stream'))
        # Refresh the target without deleting or moving directories.
        shutil.copytree(self.export.old,self.export.new,dirs_exist_ok=True)

    def interface(self,fields):
        q=interfaces.Q;root=E.Element(q+'Form',version='2.21')
        E.SubElement(root,q+'AutoCommandBar',name='FormCommandBar',id='-1');items=E.SubElement(root,q+'ChildItems')
        for index,name in enumerate(fields,1):
            node=E.SubElement(items,q+'InputField',name='Data'+name,id=str(index))
            E.SubElement(node,q+'DataPath').text='Data.'+name
        main=E.SubElement(E.SubElement(root,q+'Attributes'),q+'Attribute',name='Data',id='17')
        E.SubElement(E.SubElement(main,q+'Type'),'{'+xml_namespaces.CORE+'}Type').text='cfg:InformationRegisterRecordManager.'+self.owner_name
        E.SubElement(main,q+'MainAttribute').text='true'
        return E.tostring(root,encoding='unicode')

    def change_owner(self):
        path=self.export.new/self.export.paths[self.owner_id];root=E.parse(path);obj=root.getroot()[0]
        obj.find(self.q+'Properties/'+self.q+'InformationRegisterPeriodicity').text='Day'
        children=obj.find(self.q+'ChildObjects');attr=copy.deepcopy(children.find(self.q+'Attribute'))
        self.added_id='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
        attr.set('uuid',self.added_id);attr.find(self.q+'Properties/'+self.q+'Name').text='Added'
        children.append(attr);root.write(path,encoding='utf-8')

    def request(self):
        blocks=[];manifest=[s.atom(0),s.atom(len(self.objects))]
        for oid,docs in self.objects.items():
            meta=s.text_bytes(docs);body=s.compress(self.bodies[oid]);blocks.extend((meta,body))
            names=[s.val(value) for value in docs[0][11][1::2]]
            manifest.extend((s.atom(oid),s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(body).hexdigest(),True),s.atom(len(names))))
            for name in names:
                payload=self.externals[name];blocks.append(payload)
                manifest.extend((s.atom(name,True),s.atom(hashlib.sha1(payload).hexdigest(),True)))
        r=dict(directory=str(self.export.new),baseline_directory=str(self.export.old),platform='8.5.1.1529',
               repository='Synthetic',repository_version=self.fixture['request']['repository_version'],
               context=base64.b64encode(s.storage([s.text_bytes(d) for d in self.objects.values()],s.text_bytes([[s.atom(0)]]))).decode(),
               storage=base64.b64encode(s.storage(blocks,s.text_bytes([manifest]))).decode())
        plan,_=commit.prepare(r)
        r.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'],
                 snapshots={oid:store(self.objects[oid],self.bodies[oid]) for oid in plan['snapshot_ids']},
                 originals={oid:uuid.UUID(s.val(self.objects[oid][0][7])).bytes_le.hex()+'00000000' for oid in plan['snapshot_ids']})
        return r

    def assert_bindings(self,result,oid):
        _,records=batch.read_packet(result['data']);record=next(row for row in records if row.object_id==oid)
        interface=interfaces.interface(s.inflate(record.externals[0][1]));found={}
        def visit(node):
            if not isinstance(node,list):return
            if len(node)>12 and isinstance(node[6],s.Atom) and s.val(node[6]) in ('DataPeriod','DataAdded'):found[s.val(node[6])]=node[11]
            for child in node:visit(child)
        visit(interface[1]);self.assertEqual(s.render(found['DataPeriod']),'{2,{17},{-2}}')
        self.assertEqual(s.render(found['DataAdded']),'{2,{17},{0,'+self.added_id+'}}')
        owner=next(row for row in records if row.object_id==self.owner_id)
        body=s.Parser(s.inflate(owner.body).decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.val(body[1][18]),'4');self.assertIn(self.added_id,s.render(body))

    def test_existing_forms_use_final_owner_even_when_listed_before_it(self):
        self.change_owner()
        for oid in self.form_ids:
            path=(self.export.new/self.export.paths[oid]).with_suffix('')/'Ext/Form.xml'
            path.write_text(self.interface(('Period','Added')),encoding='utf-8')
        r=self.request();plan,changes=commit.prepare(r)
        changes.sort(key=lambda change:change['kind']=='InformationRegister')
        from unittest.mock import patch
        with patch.object(commit,'prepare',return_value=(plan,changes)):result=commit.serialize(r)
        self.assertEqual(set(result['changed_ids']),{self.owner_id,*self.form_ids})
        for oid in self.form_ids:self.assert_bindings(result,oid)

    def test_new_form_uses_changed_owner_in_the_same_packet(self):
        self.change_owner();oid='bbbbbbbb-cccc-4ddd-8eee-ffffffffffff';name='FinalOwnerForm'
        owner_path=self.export.new/self.export.paths[self.owner_id];root=E.parse(owner_path)
        E.SubElement(root.getroot()[0].find(self.q+'ChildObjects'),self.q+'Form').text=name;root.write(owner_path,encoding='utf-8')
        path=owner_path.with_suffix('')/'Forms'/(name+'.xml')
        definition=E.Element(self.q+'MetaDataObject',version='2.21');form=E.SubElement(definition,self.q+'Form',uuid=oid)
        E.SubElement(E.SubElement(form,self.q+'Properties'),self.q+'Name').text=name
        path.write_bytes(E.tostring(definition,encoding='utf-8'));ext=path.with_suffix('')/'Ext';ext.mkdir(parents=True)
        (ext/'Form.xml').write_text(self.interface(('Period','Added')),encoding='utf-8')
        request=self.request();plan,_=commit.prepare(request)
        self.assertEqual(set(plan['snapshot_ids']),{self.owner_id,*self.form_ids})
        result=commit.serialize(request);self.assertEqual(result['new_ids'],[oid]);self.assert_bindings(result,oid)

    def test_comment_only_changes_do_not_read_retained_form_snapshots(self):
        path=self.export.new/self.export.paths[self.owner_id];root=E.parse(path)
        root.getroot()[0].find(self.q+'Properties/'+self.q+'Comment').text='Only a comment'
        root.write(path,encoding='utf-8');request=self.request();plan,_=commit.prepare(request)
        self.assertEqual(plan['dependent_form_ids'],[]);self.assertEqual(plan['snapshot_ids'],[self.owner_id])
        self.assertFalse(plan['needs_storage']);self.assertEqual(commit.serialize(request)['changed_ids'],[self.owner_id])

    def rename_owner(self):
        path=self.export.new/self.export.paths[self.owner_id];name=self.owner_name+'Renamed'
        for file in self.export.new.rglob('*.xml'):
            if file.name=='ConfigDumpInfo.xml':continue
            file.write_text(file.read_text(encoding='utf-8').replace(self.owner_name,name),encoding='utf-8')
        target=path.with_name(name+'.xml');path.rename(target)
        directory=path.with_suffix('');assert self.export.new.resolve() in directory.resolve().parents
        directory.rename(target.with_suffix(''))
        return target

    def test_owner_rename_and_existing_main_forms_use_final_type_names(self):
        self.rename_owner();result=commit.serialize(self.request());_,records=batch.read_packet(result['data'])
        self.assertEqual(set(self.form_ids).intersection(result['changed_ids']),set(self.form_ids))
        for oid in self.form_ids:
            row=next(row for row in records if row.object_id==oid)
            interface=interfaces.interface(s.inflate(row.externals[0][1]));source=interfaces.interface(s.inflate(self.externals[oid+'.0']))
            from test_defined_type_forms import signature
            self.assertEqual(signature(interface),signature(source))

    def test_owner_rename_and_new_main_form_share_a_final_owner(self):
        owner=self.rename_owner();oid='bbbbbbbb-cccc-4ddd-8eee-ffffffffffff';name='NewBoundForm'
        root=E.parse(owner);E.SubElement(root.getroot()[0].find(self.q+'ChildObjects'),self.q+'Form').text=name;root.write(owner,encoding='utf-8')
        file=owner.with_suffix('')/'Forms'/(name+'.xml');definition=E.Element(self.q+'MetaDataObject',version='2.21')
        E.SubElement(E.SubElement(E.SubElement(definition,self.q+'Form',uuid=oid),self.q+'Properties'),self.q+'Name').text=name
        file.write_bytes(E.tostring(definition,encoding='utf-8'));ext=file.with_suffix('')/'Ext';ext.mkdir(parents=True)
        (ext/'Form.xml').write_text(self.interface(('Flag',)).replace(self.owner_name,self.owner_name+'Renamed'),encoding='utf-8')
        result=commit.serialize(self.request());_,records=batch.read_packet(result['data'])
        self.assertEqual(result['new_ids'],[oid]);row=next(row for row in records if row.object_id==oid)
        interface=interfaces.interface(s.inflate(row.externals[0][1]));source=interfaces.interface(s.inflate(self.externals[self.form_ids[0]+'.0']))
        self.assertEqual(s.render(interface[3]),s.render(source[3]))

    def test_explicit_owner_rename_still_checks_uuid_and_generated_types(self):
        target=copy.deepcopy(self.owner);profiles.owner_common(target,'InformationRegister')[2]=s.atom(self.owner_name+'Renamed',True)
        with self.assertRaisesRegex(ValueError,'identity'):profiles.binding_owner(self.owner,target,'InformationRegister')
        self.assertIs(profiles.binding_owner(self.owner,target,'InformationRegister',allow_rename=True),target)
        common=profiles.owner_common(target,'InformationRegister');identity=common[1][2];common[1][2]=s.atom(s.ZERO)
        with self.assertRaisesRegex(ValueError,'identity'):profiles.binding_owner(self.owner,target,'InformationRegister',allow_rename=True)
        common[1][2]=identity
        target[1][13]=s.atom(str(uuid.uuid4()))
        with self.assertRaisesRegex(ValueError,'generated types'):profiles.binding_owner(self.owner,target,'InformationRegister',allow_rename=True)

    def test_unavailable_fields_and_foreign_final_owners_reject(self):
        for oid in self.form_ids:
            path=(self.export.new/self.export.paths[oid]).with_suffix('')/'Ext/Form.xml'
            path.write_text(self.interface(('Period',)),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'DataPath'):commit.serialize(self.request())
        for mutation in ('identity','type'):
            target=copy.deepcopy(self.owner)
            if mutation=='identity':profiles.owner_common(target,'InformationRegister')[1][2]=s.atom(s.ZERO)
            else:target[1][13]=s.atom(str(uuid.uuid4()))
            with self.subTest(mutation=mutation),self.assertRaisesRegex(ValueError,'Final form owner'):
                profiles.binding_owner(self.owner,target,'InformationRegister')

    def test_removing_a_field_used_by_unchanged_forms_is_rejected(self):
        path=self.export.new/self.export.paths[self.owner_id];root=E.parse(path)
        children=root.getroot()[0].find(self.q+'ChildObjects');children.remove(children.find(self.q+'Attribute'));root.write(path,encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Retained form .* unavailable owner DataPath: Data.Flag'):
            commit.serialize(self.request())

    def test_replacing_field_identity_rebuilds_unchanged_form_streams(self):
        path=self.export.new/self.export.paths[self.owner_id];root=E.parse(path)
        attr=root.getroot()[0].find(self.q+'ChildObjects/'+self.q+'Attribute')
        replacement='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';attr.set('uuid',replacement);root.write(path,encoding='utf-8')
        r=self.request();result=commit.serialize(r);_,records=batch.read_packet(result['data'])
        self.assertEqual(set(result['changed_ids']),{self.owner_id,*self.form_ids})
        for oid in self.form_ids:
            record=next(row for row in records if row.object_id==oid)
            interface=interfaces.interface(s.inflate(record.externals[0][1]))
            self.assertIn('{2,{17},{0,'+replacement+'}}',s.render(interface[1]))
            self.assertEqual(s.val(interface[2]),'// source')
            relative=self.export.paths[oid].with_suffix('')/'Ext/Form.xml'
            self.assertEqual((self.export.old/relative).read_bytes(),(self.export.new/relative).read_bytes())

    def test_definition_only_form_change_still_rebinds_changed_owner_fields(self):
        path=self.export.new/self.export.paths[self.owner_id];root=E.parse(path)
        replacement='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
        root.getroot()[0].find(self.q+'ChildObjects/'+self.q+'Attribute').set('uuid',replacement);root.write(path,encoding='utf-8')
        for oid in self.form_ids:
            path=self.export.new/self.export.paths[oid];definition=E.parse(path)
            definition.getroot()[0].find(self.q+'Properties/'+self.q+'Comment').text='Definition only'
            definition.write(path,encoding='utf-8')
        request=self.request();_,changes=commit.prepare(request)
        self.assertTrue(all(row['content_unchanged'] for row in changes if row['object_id'] in self.form_ids))
        result=commit.serialize(request);_,records=batch.read_packet(result['data'])
        for oid in self.form_ids:
            record=next(row for row in records if row.object_id==oid)
            self.assertTrue(record.externals)
            self.assertIn('{2,{17},{0,'+replacement+'}}',s.render(interfaces.interface(s.inflate(record.externals[0][1]))[1]))

    def test_field_and_its_form_bindings_can_be_removed_in_one_packet(self):
        path=self.export.new/self.export.paths[self.owner_id];root=E.parse(path)
        children=root.getroot()[0].find(self.q+'ChildObjects');attr=children.find(self.q+'Attribute');removed=attr.get('uuid');children.remove(attr);root.write(path,encoding='utf-8')
        for oid in self.form_ids:
            file=(self.export.new/self.export.paths[oid]).with_suffix('')/'Ext/Form.xml';form=E.parse(file);items=form.getroot().find(interfaces.Q+'ChildItems')
            for field in list(items):
                if field.findtext(interfaces.Q+'DataPath')=='Data.Flag':items.remove(field)
            form.write(file,encoding='utf-8')
        result=commit.serialize(self.request());_,records=batch.read_packet(result['data'])
        for record in records:
            if record.object_id in self.form_ids:self.assertNotIn(removed,s.render(interfaces.interface(s.inflate(record.externals[0][1]))))
        owner=next(record for record in records if record.object_id==self.owner_id)
        self.assertNotIn(removed,{s.val(v) for v in s.Parser(owner.metadata.decode('utf-8-sig')).documents()[0][13][1:]})

    def test_scalar_type_change_rebuilds_forms_without_editing_their_xml(self):
        import type_description_xml as types
        path=self.export.new/self.export.paths[self.owner_id];root=E.parse(path)
        props=root.getroot()[0].find(self.q+'ChildObjects/'+self.q+'Attribute/'+self.q+'Properties')
        props.remove(props.find(self.q+'Type'));props.append(types.export(s.Parser('{"Pattern",{"D"}}').documents()[0],self.q+'Type'))
        root.write(path,encoding='utf-8');result=commit.serialize(self.request())
        self.assertEqual(set(result['changed_ids']),{self.owner_id,*self.form_ids})
        _,records=batch.read_packet(result['data'])
        for oid in self.form_ids:
            record=next(row for row in records if row.object_id==oid)
            self.assertEqual(s.val(interfaces.interface(s.inflate(record.externals[0][1]))[2]),'// source')

    def test_unused_new_fields_do_not_rewrite_unchanged_forms(self):
        self.change_owner();result=commit.serialize(self.request())
        self.assertEqual(result['changed_ids'],[self.owner_id])


if __name__=='__main__':unittest.main()
