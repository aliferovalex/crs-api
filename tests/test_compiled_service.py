"""Real HTTP service records use the common identity and CF delta readers."""
import json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_graph as graph
import compiled_image
import metadata_structure
import native_metadata as s


class CompiledServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case=json.loads(Path(__file__).with_name('fixtures').joinpath('compiled_http_service.json').read_text(encoding='utf-8'))

    def stage(self,name):
        case=self.case;row=case['stages'][name];oid=case['object_id'];parent=case['parent_id']
        record=dict(id=oid,parent_id=parent,kind='HTTPService',name='CRSAPI_HTTPService',node=E.fromstring(row['xml'])[0])
        root=dict(id=parent,parent_id=s.ZERO,kind='Configuration',name='Cfg',node=E.Element(graph.export.Q+'Configuration',uuid=parent))
        inventory={oid:record,parent:root}
        image={oid:row['body'].encode('utf-8'),oid+'.0':bytes.fromhex(row['stream_hex'])}
        return graph.TypeIndex(inventory,image),image

    def test_nested_url_and_method_features_use_the_common_native_identity_proof(self):
        ids=self.case['ids'];oid=self.case['object_id']
        for stage,expected in [('create',{ids['URLTemplate'],ids['Method']}),
                               ('edit',{ids['URLTemplate'],ids['Method'],ids['SecondMethod']}),
                               ('prune',{ids['URLTemplate'],ids['Method']})]:
            with self.subTest(stage=stage):
                index,image=self.stage(stage);facts=index.facts(oid)
                self.assertEqual(facts.class_id,metadata_structure.profile('HTTPService')['class_id'])
                self.assertEqual(set(facts.features),expected)
                self.assertEqual(facts.children,{})
                self.assertEqual(facts.parent_id,self.case['parent_id'])

    def test_method_addition_and_removal_change_the_whole_body_and_module_stream(self):
        oid=self.case['object_id']
        for before,after in [('create','edit'),('edit','prune')]:
            with self.subTest(before=before,after=after):
                _,source=self.stage(before);_,target=self.stage(after)
                delta=compiled_image.Delta(source,target,{oid},{oid},{})
                change=delta.objects[oid]
                self.assertEqual(change.operation,'change')
                self.assertTrue(change.body_changed)
                self.assertEqual(change.changed_streams,(oid+'.0',))
                self.assertEqual(change.added_streams,())
                self.assertEqual(change.removed_streams,())


if __name__=='__main__':unittest.main()
