"""Main schema assignment uses the registered children of the same Report."""
import base64
import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('object_change_serializer.py')).parent))
import object_change_serializer as changes
import metadata_object_xml as flat
import metadata_context
import metadata_identifiers
import native_metadata as s
import test_object_change_serializer as packets


class MainSchemaReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=json.loads(Path(__file__).with_name('fixtures').joinpath('main_schema_reference_851.json').read_text(encoding='utf-8'))

    def test_assignment_matches_native_and_preserves_all_children(self):
        request=copy.deepcopy(self.fixture['request']);result=changes.serialize(request)
        _,docs,body,_,_=packets.unpack(result)
        self.assertEqual(s.render(s.Parser(body.decode('utf-8-sig')).documents()),s.render(s.Parser(self.fixture['owner_body']).documents()))
        source=metadata_context.context_metadata(base64.b64decode(request['context']),request['object_id'])
        self.assertEqual(metadata_context.children(docs[0]),metadata_context.children(source[0]))
        schema_id=s.val(s.Parser(body.decode('utf-8-sig')).documents()[0][1][5])
        self.assertIn((schema_id,metadata_identifiers.class_id('Template')),metadata_context.children(docs[0]))
        self.assertEqual(s.metadata_relations(docs[0][14])[schema_id],0)

    def test_foreign_owner_and_unregistered_template_are_rejected(self):
        request=self.fixture['request'];objects=metadata_context.context_objects(request['context']);owner=objects[request['object_id']][0]
        tid=next(oid for oid,kind in metadata_context.children(owner) if kind==metadata_identifiers.class_id('Template'))
        foreign=copy.deepcopy(objects);foreign[tid][0][3]=s.atom('77777777-7777-4777-8777-777777777777')
        with self.assertRaisesRegex(ValueError,'owned child reference'):
            flat.object_xml(request['object_xml'],request['platform'],'Report',foreign)
        missing=copy.deepcopy(objects)
        rows=missing[request['object_id']][0][12]
        row=next(row for row in rows[1:] if s.val(row[0])==metadata_identifiers.class_id('Template'))
        row.remove(next(node for node in row[2:] if s.val(node)==tid));row[1]=s.atom(len(row)-2)
        with self.assertRaisesRegex(ValueError,'owned child reference'):
            flat.object_xml(request['object_xml'],request['platform'],'Report',missing)

    def test_owner_update_cannot_drop_an_existing_template(self):
        request=copy.deepcopy(self.fixture['request'])
        request['object_xml']=request['object_xml'].replace('<ns0:Template>CRSAPI_SecondSchemaTemplate</ns0:Template>','')
        self.assertNotEqual(request['object_xml'],self.fixture['request']['object_xml'])
        with self.assertRaisesRegex(ValueError,'must be preserved'):
            changes.serialize(request)


if __name__=='__main__':unittest.main()
