"""Owned trees and dependencies have distinct cycle and missing-reference rules."""
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import object_graph as g,constant_serializer as c,metadata_serializer as s
import test_constant_serializer as fixture
import base64

ROOT='11111111-1111-4111-8111-111111111111';CHILD='22222222-2222-4222-8222-222222222222';FORM='33333333-3333-4333-8333-333333333333';CLASS=c.identifiers.class_id('Catalog')

def objects():
    r=fixture.fixture('8.5.1.1529');template=next(iter(c.context_objects(r['context']).values()));result={}
    for oid,parent in [(ROOT,s.ZERO),(CHILD,ROOT),(FORM,CHILD)]:
        d=copy.deepcopy(template);m=d[0];m[1]=s.atom(oid);m[2]=s.atom(CLASS);m[3]=s.atom(parent);m[12]=[s.atom(0)];m[14]=[s.atom(0)];result[oid]=d
    result[ROOT][0][12]=[s.atom(1),[s.atom(CLASS),s.atom(1),s.atom(CHILD)]]
    result[CHILD][0][12]=[s.atom(1),[s.atom(CLASS),s.atom(1),s.atom(FORM)]]
    return result

class ObjectGraphTests(unittest.TestCase):
    def test_recursive_tree_and_bidirectional_dependencies(self):
        data=objects();data[ROOT][0][14]=[s.atom(1),s.atom(FORM),s.atom(1)];data[FORM][0][14]=[s.atom(1),s.atom(ROOT),s.atom(1)]
        self.assertEqual(g.closure(data,ROOT,c.children),[ROOT,CHILD,FORM])
        self.assertEqual(set(g.closure(data,CHILD,c.children)),{ROOT,CHILD,FORM})

    def test_missing_child_wrong_parent_and_ownership_cycle_are_rejected(self):
        for case in ('missing','parent','cycle','class'):
            data=objects()
            if case=='missing':data.pop(FORM)
            elif case=='parent':data[FORM][0][3]=s.atom(ROOT)
            elif case=='class':data[FORM][0][2]=s.atom(c.identifiers.class_id('Document'))
            else:data[FORM][0][12]=[s.atom(1),[s.atom(CLASS),s.atom(1),s.atom(ROOT)]];data[ROOT][0][3]=s.atom(FORM)
            with self.subTest(case=case),self.assertRaises(ValueError):g.closure(data,ROOT,c.children)

    def test_absent_historical_relation_is_retained_without_missing_snapshot(self):
        data=objects();data[FORM][0][14]=[s.atom(1),s.atom('99999999-9999-4999-8999-999999999999'),s.atom(1)]
        self.assertEqual(g.closure(data,ROOT,c.children),[ROOT,CHILD,FORM])

    def test_live_related_object_requires_valid_parent_registration(self):
        data=objects();data[CHILD][0][12]=[s.atom(0)];data[ROOT][0][14]=[s.atom(1),s.atom(FORM),s.atom(1)]
        with self.assertRaisesRegex(ValueError,'parent collection'):g.closure(data,ROOT,c.children)

if __name__=='__main__':unittest.main()
