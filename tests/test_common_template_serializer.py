"""Common schema templates share codecs and preserve the root's other contents."""
import base64
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('template_serializer.py')).parent))
import template_serializer as templates
import delete_owned_object_serializer as deletion
import metadata_serializer as s
import preparation_plan
from test_catalog_form_serializer import records
from test_schema_content import digest
from test_template_deletion import unpack


class CommonTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads(Path(__file__).with_name('fixtures').joinpath('common_template_packets_851.json').read_text(encoding='utf-8'))

    def test_creation_matches_native_and_root_retains_all_other_children(self):
        request=copy.deepcopy(self.data['create']);result=templates.serialize(request)
        _,child,body,external,parent,root=records(result)
        self.assertEqual(s.render(s.Parser(body.decode('utf-8-sig')).documents()),s.render(s.Parser(self.data['create_body']).documents()))
        self.assertEqual(s.render(s.Parser(root.decode('utf-8-sig')).documents()),self.data['create_root'])
        self.assertEqual([digest(p) for p in templates.schema_content.unpack(external)],self.data['create_schema'])
        previous=s.context_metadata(base64.b64decode(request['context']),request['object_id'])
        self.assertTrue(set(templates.c.children(previous[0])).issubset(set(templates.c.children(parent[0]))))
        self.assertEqual(s.val(child[0][2]),templates.ids.class_id('CommonTemplate'))
        self.assertEqual(s.metadata_relations(parent[0][14])[result['object_id']],1)

    def test_change_matches_native(self):
        result=templates.serialize(copy.deepcopy(self.data['change']))
        raw=s.inflate(base64.b64decode(result['data'])[18:]);_,pos=s.read_record(raw,0);storage,_=s.read_record(raw,pos+4)
        _,pos=s.read_record(storage,12);body,pos=s.read_record(storage,pos);external,_=s.read_record(storage,pos)
        self.assertEqual(s.render(s.Parser(s.inflate(body).decode('utf-8-sig')).documents()),s.render(s.Parser(self.data['change_body']).documents()))
        self.assertEqual([digest(p) for p in templates.schema_content.unpack(s.inflate(external))],self.data['change_schema'])

    def test_delete_matches_native_and_preserves_other_root_contents(self):
        request=copy.deepcopy(self.data['delete']);result=deletion.serialize(request);_,docs,body=unpack(result)
        self.assertEqual(s.render(s.Parser(body.decode('utf-8-sig')).documents()),self.data['delete_root'])
        source=s.context_metadata(base64.b64decode(request['context']),result['parent_id'])
        self.assertEqual(set(templates.c.children(docs[0])),set(templates.c.children(source[0]))-{(request['form_id'],templates.ids.class_id('CommonTemplate'))})

    def test_common_template_plan_uses_configuration_root(self):
        request=self.data['create']
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'Schema.xml';path.write_text(request['definition_xml'],encoding='utf-8');ext=path.with_suffix('')/'Ext';ext.mkdir(parents=True);(ext/'Template.xml').write_text(request['template_xml'],encoding='utf-8')
            result=preparation_plan.plan(dict(xml_path=str(path),context=request['context']))
            self.assertEqual((result['kind'],result['parent_id'],result['operation']),('CommonTemplate',request['object_id'],'Создание'))


if __name__=='__main__':unittest.main()
