"""Removed types must not leave incoming repository dependencies behind."""
import base64,copy,json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
import test_constant_change as constant
import test_object_change_serializer as changes
from test_managed_form_creation import store
import metadata_type_references as refs
import metadata_object_xml as metadata
import metadata_identifiers as ids
import native_metadata as s
import type_description_xml as types


class DependencyTests(unittest.TestCase):
    def test_clearing_a_command_parameter_drops_only_its_verified_dependency(self):
        import metadata_context
        import test_object_xml_profiles
        request,docs,_,oid,name,pattern=self.fixture();objects=metadata_context.context_objects(request['context'])
        top=E.fromstring(test_object_xml_profiles.xml('DataProcessor'));top[0].set('uuid',request['object_id']);m=docs[0];m[2]=s.atom(ids.class_id('DataProcessor'));m[9]=s.atom('ProfileTest',True)
        cid='eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';node=E.SubElement(top[0].find(metadata.Q+'ChildObjects'),metadata.Q+'Command',uuid=cid);props=E.SubElement(node,metadata.Q+'Properties');E.SubElement(props,metadata.Q+'Name').text='ReferencedCommand'
        props.append(types.export_metadata(pattern,metadata.Q+'CommandParameterType',{'cfg:CatalogRef.'+name:s.val(pattern[1][1])}))
        raw=metadata.create(E.tostring(top,encoding='unicode'),request['platform'],'DataProcessor',type_references={'cfg:CatalogRef.'+name:s.val(pattern[1][1])})[2]
        m[13]=[s.atom(1),s.atom(cid)];objects[request['object_id']]=docs;request['context']=base64.b64encode(s.storage([s.text_bytes(d) for d in objects.values()],s.text_bytes([[s.atom(0)]]))).decode();request['snapshot']=store(docs,raw);request['object_type']='DataProcessor'
        parameter=props.find(metadata.Q+'CommandParameterType');parameter.clear();E.SubElement(parameter,types.Q+'Type').text='xs:boolean';request['object_xml']=E.tostring(top,encoding='unicode')
        self.assertTrue(refs.needs_storage(request['object_xml'],request['context'],request['object_id']))
        _,updated,_,_,_=changes.unpack(changes.change.serialize(request))
        self.assertNotIn(oid,s.metadata_relations(updated[0][14]));self.assertEqual(s.metadata_relations(updated[0][14]),{s.val(m[3]):1})
        request['reference_snapshots']={}
        with self.assertRaisesRegex(ValueError,'snapshot is required'):changes.change.serialize(request)

    def fixture(self):
        request,docs,raw=constant.ConstantChangeTests().fixture()
        source=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        fixture=json.loads(Path(__file__).with_name('fixtures').joinpath('metadata_reference_types_851.json').read_text(encoding='utf-8'))
        case=next(row for row in fixture['cases'] if row['kind']=='Catalog');top=E.fromstring(case['xml']);oid=top[0].get('uuid');name=top[0].findtext(metadata.Q+'Properties/'+metadata.Q+'Name')
        catalog_docs=copy.deepcopy(docs);m=catalog_docs[0];m[1]=s.atom(oid);m[2]=s.atom(ids.class_id('Catalog'));m[9]=s.atom(name,True)
        import inline_object_xml
        body=s.Parser(case['body']).documents()[0];features=inline_object_xml.features(body,metadata.profiles.layout('Catalog'));m[13]=[s.atom(len(features))]+[s.atom(v) for v in features]
        pattern=[s.atom('Pattern',True),[s.atom('#',True),s.atom(fixture['references']['cfg:CatalogRef.'+name])]]
        path=metadata.profiles.layout('Constant')['type_path'];metadata.at(source,path[:-1])[path[-1]]=pattern
        docs[0][14].extend([s.atom(oid),s.atom(0)]);docs[0][14]=[s.atom(2),docs[0][14][1],s.atom(oid),s.atom(1),s.atom(0)]
        request['snapshot']=store(docs,s.native_body_bytes([source]));request['reference_snapshots']={oid:store(catalog_docs,case['body'].encode('utf-8-sig'))}
        request['context']=base64.b64encode(s.storage([s.text_bytes(docs),s.text_bytes(catalog_docs)],s.text_bytes([[s.atom(0)]]))).decode()
        return request,docs,source,oid,name,pattern

    def test_last_type_removed_drops_only_its_proven_relation(self):
        request,docs,_,oid,_,_=self.fixture()
        self.assertTrue(refs.needs_storage(request['object_xml'],request['context'],request['object_id']))
        _,updated,_,_,_=changes.unpack(changes.change.serialize(request))
        self.assertNotIn(oid,s.metadata_relations(updated[0][14]))
        self.assertEqual(s.metadata_relations(updated[0][14]),{s.val(docs[0][3]):1})
        request['reference_snapshots']={}
        with self.assertRaisesRegex(ValueError,'snapshot is required'):changes.change.serialize(request)

    def test_explicit_property_removal_does_not_leave_its_old_relation(self):
        request,_,_,oid,_,_=self.fixture();unknown='dddddddd-dddd-4ddd-8ddd-dddddddddddd'
        profile={'generated_slots':[],'reference_values':{'Reference':{'path':[0]}}}
        result=refs.reconcile(request,[s.atom(oid)],[s.atom(s.ZERO)],profile,{oid:0,unknown:0},request['object_id'],request['object_xml'])
        self.assertEqual(result,{unknown:0})

    def test_retained_type_keeps_the_relation_and_missing_source_fails(self):
        request,_,_,oid,name,pattern=self.fixture();top=E.fromstring(request['object_xml']);props=top[0].find(metadata.Q+'Properties')
        props.remove(props.find(metadata.Q+'Type'));props.append(types.export_metadata(pattern,metadata.Q+'Type',{'cfg:CatalogRef.'+name:s.val(pattern[1][1])}));request['object_xml']=E.tostring(top,encoding='unicode')
        _,updated,_,_,_=changes.unpack(changes.change.serialize(request));self.assertEqual(s.metadata_relations(updated[0][14])[oid],0)
        request['reference_snapshots']={}
        with self.assertRaisesRegex(ValueError,'snapshot is required'):changes.change.serialize(request)

    def test_unknown_and_still_used_structured_relations_are_preserved(self):
        request,_,source,oid,_,_=self.fixture();target=copy.deepcopy(source);target[1].append(s.atom(oid));unknown='dddddddd-dddd-4ddd-8ddd-dddddddddddd'
        relations={oid:0,unknown:0}
        result=refs.reconcile(request,source,target,metadata.profiles.layout('Constant'),relations,request['object_id'],request['object_xml'])
        self.assertEqual(result,{oid:0,unknown:0})


if __name__=='__main__':unittest.main()
