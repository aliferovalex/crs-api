"""Native schema template packets, existing sibling preservation and guards."""
import base64
import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(next((Path(__file__).resolve().parents[1]/'src').rglob('template_serializer.py')).parent))
import template_serializer as templates
import metadata_context
import native_metadata as s
import schema_content
import template_references
import test_catalog_form_serializer as forms
from test_schema_content import digest


class TemplatePacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads(Path(__file__).with_name('fixtures').joinpath('template_packets_851.json').read_text(encoding='utf-8'))

    def test_creation_matches_native_and_preserves_existing_form_and_template(self):
        request=copy.deepcopy(self.data['create']);result=templates.serialize(request)
        _,child,body,external,parent,owner=forms.records(result)
        self.assertEqual(s.render(s.Parser(body.decode('utf-8-sig')).documents()),s.render(s.Parser(self.data['create_body']).documents()))
        self.assertEqual(s.render(s.Parser(owner.decode('utf-8-sig')).documents()),s.render(s.Parser(self.data['create_owner']).documents()))
        self.assertEqual([digest(p) for p in schema_content.unpack(external)],self.data['create_schema'])
        previous=metadata_context.context_metadata(base64.b64decode(request['context']),request['object_id'])
        self.assertTrue(set(metadata_context.children(previous[0])).issubset(set(metadata_context.children(parent[0]))))
        self.assertEqual(s.val(child[0][3]),request['object_id'])

    def test_change_matches_native_definition_and_all_schema_parts(self):
        result=templates.serialize(copy.deepcopy(self.data['change']))
        raw=s.inflate(base64.b64decode(result['data'])[18:]);_,pos=s.read_record(raw,0);storage,_=s.read_record(raw,pos+4)
        s.validate_storage(storage);_,pos=s.read_record(storage,12);body,pos=s.read_record(storage,pos);external,_=s.read_record(storage,pos)
        self.assertEqual(s.render(s.Parser(s.inflate(body).decode('utf-8-sig')).documents()),s.render(s.Parser(self.data['change_body']).documents()))
        self.assertEqual([digest(p) for p in schema_content.unpack(s.inflate(external))],self.data['change_schema'])

    def test_unsupported_types_and_changed_source_versions_are_rejected(self):
        for operation in ('create','change'):
            for field,value in [('platform','8.5.4.1878'),('original_version','f'*40)]:
                with self.subTest(operation=operation,field=field),self.assertRaises(ValueError):
                    templates.serialize(dict(self.data[operation],**{field:value}))
        with self.assertRaisesRegex(ValueError,'DataCompositionSchema'):
            templates.serialize(dict(self.data['create'],definition_xml=self.data['create']['definition_xml'].replace('DataCompositionSchema','SpreadsheetDocument')))

    def test_invalid_owner_and_collection_are_rejected(self):
        request=copy.deepcopy(self.data['create']);docs=metadata_context.context_metadata(base64.b64decode(request['context']),request['object_id'])
        for slot in (2,12):
            bad=copy.deepcopy(docs)
            bad[0][slot]=s.atom(templates.ids.class_id('Configuration')) if slot==2 else [s.atom(0)]
            modified=dict(request,context=base64.b64encode(s.storage([s.text_bytes(bad)],s.text_bytes([[s.atom(0)]]))).decode())
            with self.subTest(slot=slot),self.assertRaises(ValueError):templates.serialize(modified)

    def test_generated_reference_is_resolved_from_current_version_and_matches_native(self):
        request=copy.deepcopy(self.data['reference_request'])
        self.assertEqual(template_references.resolve(request),(self.data['reference_types'],{}))
        result=templates.serialize(request);_,_,body,external,_,_=forms.records(result)
        self.assertEqual(s.render(s.Parser(body.decode('utf-8-sig')).documents()),s.render(s.Parser(self.data['reference_body']).documents()))
        self.assertEqual([digest(part) for part in schema_content.unpack(external)],self.data['reference_schema'])
        with self.assertRaisesRegex(ValueError,'differs from current repository'):
            template_references.resolve(dict(request,type_ids={key:'00000000-0000-0000-0000-000000000000' for key in self.data['reference_types']}))
        with self.assertRaisesRegex(ValueError,'Schema reference is missing'):
            template_references.resolve(dict(request,template_xml=request['template_xml'].replace('CatalogRef.CRSAPI_FullCatalog','CatalogRef.MissingCatalog')))

    def test_preparation_infers_template_creation_and_change(self):
        import tempfile
        import preparation_plan
        for operation in ('create','change'):
            request=self.data[operation]
            with self.subTest(operation=operation),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'Template.xml';path.write_text(request['definition_xml'],encoding='utf-8')
                ext=path.with_suffix('')/'Ext';ext.mkdir(parents=True);(ext/'Template.xml').write_text(request['template_xml'],encoding='utf-8')
                parent_id=request['object_id'] if operation=='create' else s.val(metadata_context.context_metadata(base64.b64decode(request['context']),request['object_id'])[0][3])
                result=preparation_plan.plan(dict(xml_path=str(path),context=request['context'],options=dict(parent_id=parent_id)))
                self.assertEqual(result['kind'],'Template')
                self.assertEqual(result['operation'],'Создание' if operation=='create' else 'Изменение')
                self.assertEqual(result['parent_id'],parent_id)
                self.assertEqual(result['template_xml'],request['template_xml'])

    def test_new_report_form_preserves_both_existing_templates(self):
        import managed_form_operations
        request=self.data['form_after_templates_request'];result=managed_form_operations.create(copy.deepcopy(request))
        _,_,_,_,parent,new_owner=forms.records(result)
        frame=templates.contexts.read(request,request['object_id'])
        before=metadata_context.children(frame.metadata);after=metadata_context.children(parent[0])
        self.assertTrue(set(before).issubset(set(after)))
        self.assertEqual(len(after),len(before)+1)
        previous=s.Parser(s.inflate(frame.data).decode('utf-8-sig')).documents()[0]
        current=s.Parser(new_owner.decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.render(previous[3]),s.render(current[3]))
        self.assertEqual(int(s.val(current[3][1])),2)


if __name__=='__main__':unittest.main()
