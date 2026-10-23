"""Whole owner XML infers removals, cascades, and retains supported changes."""
import copy, json, sys, unittest, uuid
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('automatic_deletion.py')).parent))
import automatic_deletion as deletion
import metadata_context
import native_metadata as s
from test_delete_object_serializer import fixture
from test_managed_form_creation import store
from test_template_deletion import unpack


def request(kind='CommonModule',cascade=False):
    r,objects,body,context=fixture(kind);oid=r['object_id'];parent=s.val(objects[oid][0][3]);removed=[oid]
    if cascade:
        child='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';docs=copy.deepcopy(objects[oid]);m=docs[0]
        m[1],m[2],m[3],m[9]=s.atom(child),s.atom(deletion.ids.class_id(kind+'Form')),s.atom(oid),s.atom('ChildForm',True)
        m[12],m[13],m[14]=[s.atom(0)],[s.atom(0)],[s.atom(1),s.atom(oid),s.atom(0)]
        objects[child]=docs;objects[oid][0][12]=[s.atom(1),[m[2],s.atom(1),m[1]]];removed.append(child);context()
    r.update(parent_id=parent,removed_ids=removed,repository='Synthetic',repository_version=str(uuid.uuid4()),
             snapshots={key:r['object_snapshot'] if key==oid else store(objects[key],b'opaque removed body') for key in removed})
    return r,objects,body,context


class AutomaticDeletionTests(unittest.TestCase):
    def test_deletion_preserves_literal_cr_in_the_full_parent_xml(self):
        r,_,_,_=request();root=E.fromstring(r['object_xml'])
        root.find('.//'+deletion.Q+'Comment').text='first\rsecond'
        r['object_xml']=deletion.xml_namespaces.serialize(root)
        result=deletion.serialize(r);_,_,body=unpack(result)
        self.assertIn('first\rsecond',body.decode('utf-8-sig'))

    def test_root_deletion_and_comment_are_one_packet(self):
        r,objects,_,_=request();root=E.fromstring(r['object_xml']);root.find('.//'+deletion.Q+'Comment').text='Automatic change'
        r['object_xml']=E.tostring(root,encoding='unicode');result=deletion.serialize(r);graph,docs,body=unpack(result)
        self.assertEqual(result['removed_ids'],r['removed_ids'])
        self.assertIn('Automatic change',body.decode('utf-8-sig'))
        self.assertNotIn(r['object_id'],[key for key,_ in metadata_context.children(docs[0])])
        self.assertNotIn(r['object_id'],[row['id'] for row in result['descriptions']])

    def test_cascade_removes_child_descriptors_and_all_snapshot_checks_apply(self):
        r,objects,_,_=request('Catalog',True);result=deletion.serialize(r);graph,docs,body=unpack(result)
        flags={s.val(graph[4][i]):s.val(graph[4][i+1]) for i in range(1,len(graph[4]),2)}
        self.assertEqual([flags[key] for key in r['removed_ids']],['0','0'])
        bad=copy.deepcopy(r);bad['snapshots'].pop(r['removed_ids'][1])
        with self.assertRaises(KeyError):deletion.serialize(bad)
        bad=copy.deepcopy(r);old=copy.deepcopy(objects[r['removed_ids'][1]]);old[0][7]=s.atom(str(uuid.uuid4()))
        bad['snapshots'][r['removed_ids'][1]]=store(old,b'old')
        with self.assertRaisesRegex(ValueError,'mismatch'):deletion.serialize(bad)

    def test_external_references_into_deleted_subtree_fail(self):
        r,objects,_,context=request('Catalog',True)
        other=next(key for key in objects if key not in set(r['removed_ids'])|{r['parent_id']})
        objects[other][0][14]=[s.atom(1),s.atom(r['removed_ids'][1]),s.atom(0)];context()
        with self.assertRaisesRegex(ValueError,'incoming references'):deletion.serialize(r)

    def test_catalog_form_absence_and_property_change(self):
        import test_delete_form_serializer as forms
        r,before=forms.fixture();objects=metadata_context.context_objects(r['context']);oid=r['form_id'];parent=s.val(objects[oid][0][3])
        root=E.fromstring(r['object_xml']);root.find('.//'+deletion.Q+'Comment').text='Owner comment'
        r.update(parent_id=parent,removed_ids=[oid],repository='Synthetic',repository_version=str(uuid.uuid4()),object_xml=E.tostring(root,encoding='unicode'),snapshots={oid:r['form_snapshot']})
        result=deletion.serialize(r);_,_,body=unpack(result)
        self.assertEqual(result['removed_ids'],[oid]);self.assertIn('Owner comment',body.decode('utf-8-sig'))
        self.assertEqual(s.val(s.Parser(body.decode('utf-8-sig')).documents()[0][7][1]),'0')

    def test_missing_section_duplicate_and_plan_change_fail(self):
        r,objects,_,_=request();root=E.fromstring(r['object_xml']);root[0].remove(root[0].find(deletion.Q+'ChildObjects'))
        with self.assertRaisesRegex(ValueError,'requires ChildObjects'):deletion.missing(E.tostring(root,encoding='unicode'),r['parent_id'],objects)
        bad=dict(r,removed_ids=[])
        with self.assertRaisesRegex(ValueError,'plan changed'):deletion.serialize(bad)
        root=E.fromstring(r['object_xml']);children=root[0].find(deletion.Q+'ChildObjects');children.append(copy.deepcopy(children[0]))
        with self.assertRaisesRegex(ValueError,'Duplicate'):deletion.missing(E.tostring(root,encoding='unicode'),r['parent_id'],objects)

    def test_owner_modules_are_updated_in_same_packet_as_form_removal(self):
        import test_delete_owner_forms as owners
        cases=json.loads(Path(__file__).with_name('fixtures').joinpath('owner_forms_851.json').read_text(encoding='utf-8'))['cases']
        for case in cases:
            with self.subTest(kind=case['kind']):
                r,_=owners.request(case);oid=r['form_id'];objects=metadata_context.context_objects(r['context']);parent=s.val(objects[oid][0][3])
                r.update(parent_id=parent,removed_ids=[oid],repository='Synthetic',repository_version=str(uuid.uuid4()),snapshots={oid:r['form_snapshot']},modules={'ObjectModule':'// Updated while removing form'})
                result=deletion.serialize(r)
                self.assertEqual(result['removed_ids'],[oid])
                actions={row['name']:row['action'] for row in result['externals']}
                self.assertEqual(actions[parent+'.0'],1);self.assertEqual(actions[parent+'.2'],0)


if __name__=='__main__':unittest.main()
