"""Three real subsystem levels share the generic stored-collection reader."""
import json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_graph as graph
import metadata_structure
import native_metadata as s


class SubsystemTests(unittest.TestCase):
    def setUp(self):
        self.case=json.loads(Path(__file__).with_name('fixtures').joinpath('compiled_subsystems.json').read_text(encoding='utf-8'))
        self.inventory={row['id']:dict(id=row['id'],parent_id=row['parent_id'],name=row['name'],kind='Subsystem',node=E.fromstring(row['xml'])[0]) for row in self.case['objects']}
        root=self.case['root_id'];self.inventory[root]=dict(id=root,parent_id=s.ZERO,name='Cfg',kind='Configuration',node=E.Element(graph.export.Q+'Configuration',uuid=root))
        self.image={row['id']:row['body'].encode('utf-8') for row in self.case['objects']}

    def test_recursive_parent_and_child_collections_match_declared_ownership(self):
        index=graph.TypeIndex(self.inventory,self.image);cls=metadata_structure.profile('Subsystem')['class_id']
        for row in self.case['objects']:
            facts=index.facts(row['id'])
            expected={oid for oid,item in self.inventory.items() if item['parent_id']==row['id']}
            self.assertEqual(facts.class_id,cls)
            self.assertEqual(facts.parent_id,row['parent_id'])
            self.assertEqual(set(facts.children[cls]),expected)
            self.assertEqual(facts.features,())

    def test_native_parent_cannot_silently_point_to_another_subsystem(self):
        parent=next(row for row in self.case['objects'] if row['parent_id']==self.case['root_id'])
        child=next(row for row in self.case['objects'] if row['parent_id']==parent['id'])
        self.image[parent['id']]=self.image[parent['id']].replace(child['id'].encode(),b'55555555-5555-4555-8555-555555555555')
        with self.assertRaisesRegex(ValueError,'stored children differ'):
            graph.TypeIndex(self.inventory,self.image).facts(parent['id'])


if __name__=='__main__':unittest.main()
