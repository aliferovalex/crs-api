"""General deletion reuses native root collections and protects dependencies."""
import base64,copy,json,sys,tempfile,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('delete_object_serializer.py')).parent))
import delete_object_serializer as deletion
import metadata_context
import xml_namespaces
import native_metadata as s
import preparation_plan
from test_managed_form_creation import store
from test_template_deletion import unpack


def fixture(kind):
    data=json.loads(Path(__file__).with_name('fixtures').joinpath('common_template_packets_851.json').read_text(encoding='utf-8'))
    r=copy.deepcopy(data['delete']);objects=metadata_context.context_objects(r['context']);oid=r.pop('form_id');parent=s.val(objects[oid][0][3])
    cls=deletion.ids.class_id('CommonTemplate');new_cls=deletion.ids.class_id(kind)
    raw=s.inflate(s.read_record(base64.b64decode(r['snapshot']),s.read_record(base64.b64decode(r['snapshot']),12)[1])[0])
    body=s.Parser(raw.decode('utf-8-sig')).documents()[0]
    def reclassify(node):
        if not isinstance(node,list):return
        if len(node)>=2 and not isinstance(node[0],list) and s.val(node[0]) in (cls,new_cls):
            kept=[v for v in node[2:] if s.val(v)!=oid]
            if s.val(node[0])==new_cls:kept.append(s.atom(oid))
            node[:]=[node[0],s.atom(len(kept))]+kept
        else:
            for v in node:reclassify(v)
    reclassify(body)
    objects[oid][0][2]=s.atom(new_cls)
    positions=[int(s.val(d[0][10])) for key,d in objects.items() if key!=oid and s.val(d[0][3])==parent and s.val(d[0][2])==new_cls]
    objects[oid][0][10]=s.atom(max(positions,default=-1)+1)
    rows={}
    for child,child_class in metadata_context.children(objects[parent][0]):
        rows.setdefault(new_cls if child==oid else child_class,[]).append(child)
    objects[parent][0][12]=[s.atom(len(rows))]+[[s.atom(key),s.atom(len(children))]+[s.atom(child) for child in children] for key,children in rows.items()]
    root=E.fromstring(r['object_xml'])
    r.update(object_id=oid,object_snapshot=r.pop('form_snapshot'),object_original_version=r.pop('form_original_version'),
             object_xml=E.tostring(root,encoding='unicode'),snapshot=store(objects[parent],s.native_body_bytes([body])))
    # Generated type identities are required to check retained external streams.
    r['object_snapshot']=store(objects[oid],b'opaque native deleted body')
    import metadata_object_xml as metadata
    import test_object_xml_profiles as profile_cases
    import test_object_creation_serializer as constants
    if kind in metadata.profiles.profiles() and metadata.profiles.layout(kind)['generated_slots']:
        top=E.fromstring(constants.xml() if kind=='Constant' else profile_cases.xml(kind));top[0].set('uuid',oid);top[0].find(metadata.Q+'Properties/'+metadata.Q+'Name').text=s.val(objects[oid][0][9])
        r['object_snapshot']=store(objects[oid],metadata.object_xml(E.tostring(top,encoding='unicode'),r['platform'],kind)[2])
    import native_version_fixture
    r['storage']=native_version_fixture.storage(objects)
    def context():r['context']=base64.b64encode(s.storage([s.text_bytes(d) for d in objects.values()],s.text_bytes([[s.atom(0)]]))).decode()
    context()
    return r,objects,body,context


class ObjectDeletionTests(unittest.TestCase):
    def test_root_classes_share_deletion_and_preserve_unrelated_native_fields(self):
        for kind in ('Constant','CommonModule','Catalog','Document','Enum','Report','DataProcessor','Role','HTTPService','DefinedType'):
            with self.subTest(kind=kind):
                r,objects,before,_=fixture(kind);result=deletion.serialize(r);graph,docs,body=unpack(result)
                after=s.Parser(body.decode('utf-8-sig')).documents()[0]
                def expected(node):
                    if isinstance(node,list):
                        if len(node)>=2 and not isinstance(node[0],list) and s.val(node[0])==deletion.ids.class_id(kind):
                            kept=[v for v in node[2:] if s.val(v)!=r['object_id']]
                            return [node[0],s.atom(len(kept))]+kept
                        return [expected(v) for v in node]
                    return node
                self.assertEqual(s.render(after),s.render(expected(before)))
                self.assertNotIn(r['object_id'],[d['id'] for d in result['descriptions']])
                self.assertNotIn(r['object_id'],[child for child,_ in metadata_context.children(docs[0])])
                with tempfile.TemporaryDirectory() as directory:
                    path=Path(directory)/'Configuration.xml';path.write_text(r['object_xml'],encoding='utf-8')
                    plan=preparation_plan.plan(dict(xml_path=str(path),context=r['context'],options={'operation':'Удаление','object_id':r['object_id']}))
                    self.assertEqual(plan['kind'],kind)

    def test_incoming_references_and_children_are_rejected(self):
        r,objects,_,context=fixture('Enum');other=next(key for key in objects if key not in (r['object_id'],s.val(objects[r['object_id']][0][3])))
        objects[other][0][14]=[s.atom(1),s.atom(r['object_id']),s.atom(0)];context()
        with self.assertRaisesRegex(ValueError,'incoming references'):deletion.serialize(r)
        objects[other][0][14]=[s.atom(0)];objects[other][0][3]=s.atom(r['object_id']);context()
        with self.assertRaisesRegex(ValueError,'has children'):deletion.serialize(r)

    def test_feature_references_and_owner_selection_are_rejected(self):
        r,objects,_,context=fixture('Enum');oid=r['object_id'];parent=s.val(objects[oid][0][3]);feature='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
        objects[oid][0][13]=[s.atom(1),s.atom(feature)]
        other=next(key for key in objects if key not in (oid,parent));objects[other][0][14]=[s.atom(1),s.atom(feature),s.atom(0)];context()
        with self.assertRaisesRegex(ValueError,'incoming references'):deletion.serialize(r)
        objects[other][0][14]=[s.atom(0)];objects[parent][0][14]=[s.atom(1),s.atom(oid),s.atom(0)];context()
        with self.assertRaisesRegex(ValueError,'owner reference'):deletion.serialize(r)

    def test_identity_stale_snapshot_and_target_xml_are_protected(self):
        r,objects,_,context=fixture('CommonModule')
        with self.assertRaisesRegex(ValueError,'source version'):deletion.serialize(dict(r,object_original_version='f'*40))
        with self.assertRaisesRegex(ValueError,'root'):deletion.deletion_target(objects,s.val(objects[r['object_id']][0][3]))
        with self.assertRaisesRegex(ValueError,'missing'):deletion.deletion_target(objects,'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee')
        root=E.fromstring(r['object_xml']);root.find('.//{'+xml_namespaces.MD+'}Comment').text='unrelated'
        with self.assertRaises(ValueError):deletion.serialize(dict(r,object_xml=E.tostring(root,encoding='unicode')))


if __name__=='__main__':unittest.main()
