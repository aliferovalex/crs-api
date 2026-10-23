"""Whole-export template creation uses the shared final graph and native codecs."""
import base64
import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as E

import test_configuration_commit
import configuration_commit as commit
import configuration_export as export
import configuration_batch as batch
import metadata_context
import metadata_identifiers as ids
import metadata_structure
import native_metadata as s
import packet_builder as packets
import template_content
import template_serializer
from test_managed_form_creation import store


class ConfigurationTemplateTests(unittest.TestCase):
    def fixture(self,common=False,reference=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        folder=Path(temp.name);old=folder/'baseline';new=folder/'target';old.mkdir()
        name='common_template_packets_851.json' if common else 'template_packets_851.json'
        source=json.loads(Path(__file__).with_name('fixtures').joinpath(name).read_text(encoding='utf-8'))['reference_request' if reference else 'create']
        objects=metadata_context.context_objects(source['context']);paths={};q=export.Q
        root=next(oid for oid,docs in objects.items() if s.val(docs[0][3])==s.ZERO)
        def write(oid,path):
            m=objects[oid][0];kind=ids.class_labels()[s.val(m[2])]
            tag='Form' if kind.endswith('Form') and kind!='CommonForm' else metadata_structure.profile(kind)['xml_name']
            top=E.Element(q+'MetaDataObject',version='2.21');obj=E.SubElement(top,q+tag,uuid=oid)
            props=E.SubElement(obj,q+'Properties');E.SubElement(props,q+'Name').text=s.val(m[9]);E.SubElement(props,q+'Comment')
            if tag in ('Template','CommonTemplate'):E.SubElement(props,q+'TemplateType').text='BinaryData'
            children=E.SubElement(obj,q+'ChildObjects')
            for child,cls in metadata_context.children(m):
                label=ids.class_labels()[cls];ct='Form' if label.endswith('Form') and label!='CommonForm' else metadata_structure.profile(label)['xml_name']
                cname=s.val(objects[child][0][9]);E.SubElement(children,q+ct).text=cname
                write(child,(Path('') if oid==root else path.with_suffix(''))/export.folder(ct)/(cname+'.xml'))
            file=old/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(E.tostring(top,encoding='utf-8'));paths[oid]=path
            if tag in ('Form','CommonForm'):
                ext=file.with_suffix('')/'Ext';ext.mkdir(parents=True);(ext/'Form.xml').write_text('<Form/>',encoding='utf-8')
            if tag in ('Template','CommonTemplate'):
                ext=file.with_suffix('')/'Ext';ext.mkdir(parents=True);(ext/'Template.bin').write_bytes(b'unchanged opaque bytes')
        write(root,Path('Configuration.xml'))
        info=E.Element(export.D+'ConfigDumpInfo',format='Hierarchical',version='2.21');versions=E.SubElement(info,export.D+'ConfigVersions')
        for oid,docs in objects.items():
            m=docs[0];E.SubElement(versions,export.D+'Metadata',id=oid,configVersion=uuid.UUID(s.val(m[8])).bytes_le.hex()+'00000000')
            for i in range(1,len(m[11]),2):E.SubElement(versions,export.D+'Metadata',id=s.val(m[11][i]),configVersion=uuid.UUID(s.val(m[11][i+1])).bytes_le.hex()+'00000000')
        (old/'ConfigDumpInfo.xml').write_bytes(E.tostring(info,encoding='utf-8'));shutil.copytree(old,new)
        oid=source['object_id']
        request=dict(platform=source['platform'],context=source['context'],directory=str(new),baseline_directory=str(old),
                     repository='Synthetic',repository_version=str(uuid.uuid4()),snapshots={oid:source['snapshot']},originals={oid:source['original_version']})
        return request,source,objects,paths,new

    def add(self,request,source,objects,paths,target,typ,index):
        q=export.Q;parent=source['object_id'];parent_file=target/paths[parent];top=E.parse(parent_file)
        tag='CommonTemplate' if s.val(objects[parent][0][3])==s.ZERO else 'Template'
        oid=str(uuid.UUID(int=0xaaaaaaaa000040008000000000000000+index));name='WholeTemplate'+str(index)
        E.SubElement(top.getroot()[0].find(q+'ChildObjects'),q+tag).text=name;top.write(parent_file,encoding='utf-8')
        definition=E.fromstring(source['definition_xml']);definition[0].set('uuid',oid)
        props=definition[0].find(q+'Properties');props.find(q+'Name').text=name;props.find(q+'TemplateType').text=typ
        path=(Path('') if tag=='CommonTemplate' else paths[parent].with_suffix(''))/export.folder(tag)/(name+'.xml')
        file=target/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(E.tostring(definition,encoding='utf-8'))
        ext=file.with_suffix('')/'Ext';ext.mkdir(parents=True)
        raw=source['template_xml'].encode('utf-8') if typ=='DataCompositionSchema' else bytes(range(256)) if typ=='BinaryData' else 'Whole text\r\nsecond line\n'.encode('utf-8-sig')
        (ext/template_content.PROFILES[typ]['file']).write_bytes(raw)
        return oid,file

    def test_all_supported_kinds_join_one_packet_for_existing_owners_and_root(self):
        for common in (False,True):
            with self.subTest(common=common):
                r,source,objects,paths,target=self.fixture(common)
                added=[self.add(r,source,objects,paths,target,typ,index+1) for index,typ in enumerate(template_content.PROFILES)]
                plan,_=commit.prepare(r)
                self.assertEqual(set(plan['snapshot_ids']),{source['object_id']})
                self.assertFalse(plan['needs_storage'])
                r.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
                with patch.object(packets,'assemble',wraps=packets.assemble) as assemble:
                    result=commit.serialize(r);self.assertEqual(assemble.call_count,1)
                self.assertEqual(set(result['new_ids']),{oid for oid,_ in added});self.assertEqual(result['changed_ids'],[source['object_id']])
                _,records=batch.read_packet(result['data']);by_id={row.object_id:row for row in records}
                parent=s.Parser(by_id[source['object_id']].metadata.decode('utf-8-sig')).documents()[0]
                children={oid for oid,_ in metadata_context.children(parent)}
                old_count=sum(cls==ids.class_id('CommonTemplate' if common else 'Template') for _,cls in metadata_context.children(objects[source['object_id']][0]))
                for index,(oid,file) in enumerate(added):
                    record=by_id[oid];metadata=s.Parser(record.metadata.decode('utf-8-sig')).documents()
                    self.assertIn(oid,children);self.assertEqual(s.val(metadata[0][10]),str(old_count+index))
                    definition=file.read_text(encoding='utf-8');expected=template_serializer.native_definition(definition,r['platform'])[2]
                    self.assertEqual(s.inflate(record.body),expected)
                    call=dict(r,definition_xml=definition,**template_content.companion(file,definition))
                    self.assertEqual(record.externals[0][0],oid+'.0')
                    self.assertEqual(s.inflate(record.externals[0][1]),template_content.convert(call))
                    self.assertEqual(next(e for e in result['externals'] if e['object_id']==oid)['action'],0)

    def test_missing_companion_and_uuid_collision_reject_before_commit(self):
        r,source,objects,paths,target=self.fixture(True);oid,file=self.add(r,source,objects,paths,target,'BinaryData',1)
        companion=file.with_suffix('')/'Ext/Template.bin';companion.unlink()
        with self.assertRaisesRegex(ValueError,'Missing or oversized template companion'):commit.prepare(r)
        companion.write_bytes(b'bytes');top=E.parse(file);top.getroot()[0].set('uuid',source['object_id']);top.write(file,encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Duplicate export object UUID'):commit.prepare(r)

    def test_template_creation_and_sibling_deletion_share_final_positions(self):
        r,source,objects,paths,target=self.fixture()
        parent=source['object_id'];removed=next(oid for oid,cls in metadata_context.children(objects[parent][0]) if cls==ids.class_id('Template'))
        file=target/paths[removed];assert target.resolve() in file.with_suffix('').resolve().parents
        file.unlink();shutil.rmtree(file.with_suffix(''))
        owner=target/paths[parent];top=E.parse(owner);children=top.getroot()[0].find(export.Q+'ChildObjects')
        children.remove(next(node for node in children if node.tag==export.Q+'Template' and node.text==s.val(objects[removed][0][9])));top.write(owner,encoding='utf-8')
        created,_=self.add(r,source,objects,paths,target,'BinaryData',1)
        r['snapshots'][removed]=store(objects[removed],b'opaque deleted template');r['originals'][removed]=uuid.UUID(s.val(objects[removed][0][7])).bytes_le.hex()+'00000000'
        import native_version_fixture
        r['storage']=native_version_fixture.storage(objects)
        plan,_=commit.prepare(r);r.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
        result=commit.serialize(r);self.assertEqual(result['removed_ids'],[removed]);self.assertEqual(result['new_ids'],[created])
        self.assertEqual(next(row for row in result['descriptions'] if row['id']==created)['pos'],0)
        self.assertNotIn(removed,[row['id'] for row in result['requested']])

    def test_new_schema_requests_and_uses_verified_reference_storage(self):
        r,source,objects,paths,target=self.fixture(reference=True)
        created,_=self.add(r,source,objects,paths,target,'DataCompositionSchema',1)
        plan,_=commit.prepare(r);self.assertTrue(plan['needs_storage'])
        r.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
        r['storage']=source['storage'];result=commit.serialize(r)
        _,records=batch.read_packet(result['data']);record=next(row for row in records if row.object_id==created)
        expected=template_content.convert(source)
        self.assertEqual(s.inflate(record.externals[0][1]),expected)


if __name__=='__main__':unittest.main()
