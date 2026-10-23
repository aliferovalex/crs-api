"""Complete exports clear optional text without losing module/form definitions."""
import base64,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import commonmodule_serializer as modules
import configuration_commit as commit
import configuration_batch as batch
import metadata_context
import managed_form_xml as forms
import external_data
import native_metadata as s
import object_creation_serializer as creation
import test_commonmodule_change as common_cases
import test_commonmodule_serializer as new_common
import test_managed_form_operations as form_cases
import test_configuration_export as export_cases
from test_managed_form_creation import store


class SpecialModuleClearTests(unittest.TestCase):
    def test_common_module_clear_removes_its_stream_and_supports_restoring_text(self):
        request=common_cases.fixture();content=modules.compile_change(dict(request,source_text='',clear_module_text=True))
        self.assertEqual(s.render(content.docs[0][11]),'{0}');self.assertEqual(content.streams,[]);self.assertEqual(content.externals,[])
        docs=content.docs;docs[2]=[s.atom(0)];request.update(snapshot=store(docs,content.body),context=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode())
        restored=modules.compile_change(dict(request,source_text='// restored module'))
        self.assertEqual(len(restored.streams),1);self.assertEqual(restored.body,content.body)
        text=new_common.container_members(s.inflate(restored.streams[0][1]))['text'].decode('utf-8-sig');self.assertEqual(text,'// restored module')
        with self.assertRaisesRegex(ValueError,'empty source'):modules.compile_change(dict(request,source_text='conflict',clear_module_text=True))

    def test_new_empty_common_module_needs_no_source_stream(self):
        request=new_common.fixture();request.update(source_text='',clear_module_text=True);result=creation.serialize(request);_,records=batch.read_packet(result['data'])
        record=next(record for record in records if record.object_id==result['object_id']);self.assertEqual(record.externals,())
        docs=s.Parser(record.metadata.decode('utf-8-sig')).documents();self.assertEqual(s.render(docs[0][11]),'{0}')

    def test_module_only_form_update_preserves_native_interface_without_xml_mapping(self):
        request=form_cases.fixture();oid=request['object_id'];objects=metadata_context.context_objects(request['context']);parent=s.val(objects[oid][0][3])
        definition=E.Element(commit.preparation.Q+'MetaDataObject',version='2.21');node=E.SubElement(definition,commit.preparation.Q+'Form',uuid=oid);E.SubElement(E.SubElement(node,commit.preparation.Q+'Properties'),commit.preparation.Q+'Name').text='Form'
        change=dict(kind='CatalogForm',object_id=oid,object_xml=E.tostring(definition,encoding='unicode'),form_xml='<UnsupportedFormXML/>',module_text='',interface_unchanged=True)
        request.update(originals={oid:request['original_version']},snapshots={oid:request['snapshot']})
        content=commit.content(request,change,objects);previous=external_data.extract(base64.b64decode(request['storage']),oid)
        before=forms.interface(s.inflate(base64.b64decode(previous['externals'][0]['data'])));after=forms.interface(s.inflate(content.streams[0][1]));before[2]=s.atom('',True)
        self.assertEqual(s.render(before),s.render(after))
        with self.assertRaises(ValueError):commit.content(request,change,objects,owner_bodies={parent:None})

    def test_export_plan_marks_form_text_clear_without_interface_changes(self):
        helper=export_cases.ConfigurationExportTests();helper.setUp();self.addCleanup(helper.doCleanups)
        oid=helper.fixture['remaining_form_id'];file=helper.new/helper.paths[oid];(file.with_suffix('')/'Ext/Form/Module.bsl').unlink()
        request=dict(directory=str(helper.new),baseline_directory=str(helper.old),context=helper.context,platform='8.5.1.1529')
        plan,changes=commit.prepare(request);self.assertTrue(plan['operations'][0]['clear_module_text']);self.assertEqual(changes[0]['module_text'],'');self.assertTrue(changes[0]['interface_unchanged'])


if __name__=='__main__':unittest.main()
