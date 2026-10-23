"""Whole BasedOn lists share native representation and namespace-aware refs."""
import copy,json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
import test_document_serializer
import metadata_object_xml as objects
import metadata_targets,metadata_identifiers as ids,native_metadata as s


class BasedOnTests(unittest.TestCase):
    def samples(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('based_on_851.json').read_text(encoding='utf-8'))['samples']
    def targets(self):return metadata_targets.Index(metadata_targets.Target(row['id'],ids.class_id(row['kind']),s.ZERO,s.ZERO,row['name']) for row in self.samples())

    def test_complete_bodies_and_inverse_xml_match_independent_native_data(self):
        for row in self.samples():
            with self.subTest(kind=row['kind'],case=row['label']):
                raw=objects.create(row['xml'],'8.5.1.1529',row['kind'],objects=self.targets())[2]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(row['body']).documents()))
                top=objects.export(s.Parser(row['body']).documents()[0],{},'8.5.1.1529',row['kind'],objects=self.targets())
                self.assertEqual(objects.create(E.tostring(top,encoding='unicode'),'8.5.1.1529',row['kind'],objects=self.targets())[2],raw)

    def test_whole_changes_replace_clear_and_reorder_lists(self):
        rows=self.samples()
        for kind in ('Catalog','Document','ChartOfAccounts'):
            before=next(r for r in rows if r['kind']==kind and r['label']=='Mixed');source=s.Parser(before['body']).documents()[0];layout=objects.profiles.layout(kind);path=layout['reference_lists']['BasedOn']['path']
            for label in ('Default','FromCatalog','FromDocument','FromAccounts','Reverse'):
                row=next(r for r in rows if r['kind']==kind and r['label']==label);top=E.fromstring(before['xml']);props=top[0].find(objects.Q+'Properties');props.remove(props.find(objects.Q+'BasedOn'));node=copy.deepcopy(E.fromstring(row['xml'])[0].find(objects.Q+'Properties/'+objects.Q+'BasedOn'));props.append(node);top.set('xmlns:xr','http://v8.1c.ru/8.3/xcf/readable')
                raw,_=objects.change(E.tostring(top,encoding='unicode'),'8.5.1.1529',kind,source,reference_objects=self.targets());actual=s.Parser(raw.decode('utf-8-sig')).documents()[0];expected=copy.deepcopy(source);objects.at(expected,path[:-1])[path[-1]]=copy.deepcopy(objects.at(s.Parser(row['body']).documents()[0],path))
                self.assertEqual(s.render(actual),s.render(expected))

    def test_reference_type_prefix_is_resolved_and_wrong_namespace_rejects(self):
        row=next(r for r in self.samples() if r['kind']=='Document' and r['label']=='FromCatalog');xml=row['xml'];raw=objects.create(xml,'8.5.1.1529','Document',objects=self.targets())[2]
        top=E.fromstring(xml);top.set('xmlns:alias','http://v8.1c.ru/8.3/xcf/readable');top[0].find(objects.Q+'Properties/'+objects.Q+'BasedOn')[0].set('{http://www.w3.org/2001/XMLSchema-instance}type','alias:MDObjectRef');text=E.tostring(top,encoding='unicode');self.assertEqual(objects.create(text,'8.5.1.1529','Document',objects=self.targets())[2],raw)
        with self.assertRaises(ValueError):objects.create(text.replace('xmlns:alias="http://v8.1c.ru/8.3/xcf/readable"','xmlns:alias="urn:wrong"'),'8.5.1.1529','Document',objects=self.targets())

    def test_unknown_duplicate_and_unsupported_reference_class_reject(self):
        row=next(r for r in self.samples() if r['label']=='Mixed');root=E.fromstring(row['xml']);root.set('xmlns:xr','http://v8.1c.ru/8.3/xcf/readable');node=root[0].find(objects.Q+'Properties/'+objects.Q+'BasedOn')
        for value in ('Document.Missing','CommonModule.Missing'):
            top=copy.deepcopy(root);top[0].find(objects.Q+'Properties/'+objects.Q+'BasedOn')[0].text=value
            with self.assertRaises(ValueError):objects.create(E.tostring(top,encoding='unicode'),'8.5.1.1529',row['kind'],objects=self.targets())
        node.append(copy.deepcopy(node[0]))
        with self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529',row['kind'],objects=self.targets())

    def test_redeclared_self_identity_must_be_unambiguous_and_consistent(self):
        row=next(r for r in self.samples() if r['label']=='Self');targets=self.targets();own=next(t for t in targets.targets if t.object_id==row['id'])
        for extra in (own,metadata_targets.Target(own.object_id,own.class_id,own.parent_id,own.owner_id,'WrongName')):
            bad=metadata_targets.Index(list(targets.targets)+[extra])
            with self.assertRaisesRegex(ValueError,'Conflicting creation reference identity'):objects.create(row['xml'],'8.5.1.1529',row['kind'],objects=bad)

    def test_common_reference_dependency_policy_matches_native_graphs_including_self(self):
        for row in self.samples():
            body=s.Parser(row['body']).documents()[0];expected={key:flag for key,flag in row['native_relations'].items() if flag!=1}
            self.assertEqual(objects.reference_dependencies(body,objects.profiles.layout(row['kind']),row['id']),expected)

    def test_existing_object_packet_keeps_self_reference_out_of_dependency_graph(self):
        import test_object_change_serializer as fixture
        request,docs,_=fixture.fixture('Catalog');root=E.fromstring(request['object_xml']);props=root[0].find(objects.Q+'Properties');name=props.findtext(objects.Q+'Name');node=E.SubElement(props,objects.Q+'BasedOn');E.SubElement(node,'{http://v8.1c.ru/8.3/xcf/readable}Item').text='Catalog.'+name;request['object_xml']=E.tostring(root,encoding='unicode')
        result=fixture.change.serialize(request);_,new,raw,_,_=fixture.unpack(result)
        self.assertEqual(s.metadata_relations(new[0][14]),s.metadata_relations(docs[0][14]));self.assertNotIn(request['object_id'],s.metadata_relations(new[0][14]))
        body=s.Parser(raw.decode('utf-8-sig')).documents()[0];row=objects.at(body,objects.profiles.layout('Catalog')['reference_lists']['BasedOn']['path'])
        self.assertEqual(s.val(row[2][2][1]),request['object_id'])
