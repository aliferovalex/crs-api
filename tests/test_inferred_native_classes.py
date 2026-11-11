"""Schema-free class binding against independently verified native CF records."""
import base64,json,sys,unittest,zlib
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_graph as graph
import configuration_export as export
import metadata_structure
import native_metadata as s
import native_object_reader


class InferredNativeClassesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('inferred_native_classes.json').read_text(encoding='utf-8'))
        cls.cases=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))['cases']

    def inputs(self,case):
        records={row['id']:dict(row,node=E.fromstring(row['xml'])[0]) for row in case['records']}
        return records,{name:text.encode() for name,text in case['image'].items()}

    def test_native_member_collection_determines_the_server_class_and_full_graph(self):
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                self.assertIsNone(metadata_structure.profile(case['kind'])['class_id'])
                records,image=self.inputs(case);index=graph.TypeIndex(records,image)
                for oid in records:index.facts(oid)
                child=index.facts(case['child_id']);parent=index.facts(case['parent_id'])
                self.assertEqual(child.class_id,case['server_class'])
                self.assertEqual(child.parent_id,case['parent_id'])
                self.assertEqual(parent.children[child.class_id],[child.object_id])
                self.assertEqual(export.class_id(records[child.object_id],records),case['server_class'])

    def test_known_class_proves_empty_collection_before_creation_and_after_last_deletion(self):
        for case in self.cases:
            records,_=self.inputs(case);kind=records[case['parent_id']]['kind']
            for phase in ('empty_before','empty_after'):
                with self.subTest(kind=case['kind'],phase=phase):
                    body=s.Parser(case[phase]).documents()
                    groups=native_object_reader.stored_collections(body,kind,(case['server_class'],))
                    self.assertEqual(groups[case['server_class']],[])

    def test_duplicate_collection_in_real_parent_is_rejected_before_class_binding(self):
        for case in self.cases:
            records,image=self.inputs(case)
            body=s.Parser(image[case['parent_id']].decode('utf-8-sig')).documents()
            body.append([s.atom(case['server_class']),s.atom(1),s.atom(case['child_id'])])
            image[case['parent_id']]=s.native_body_bytes(body)
            with self.subTest(kind=case['kind']),self.assertRaisesRegex(ValueError,'Missing or ambiguous'):
                graph.TypeIndex(records,image)


if __name__=='__main__':unittest.main()
