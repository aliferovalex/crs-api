"""Common identity facts must be declared in XML and proven by native records."""
import json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_graph as graph
import native_metadata as s
import metadata_structure
import metadata_type_references
import form_attribute_types
import metadata_identifiers
import metadata_type_sets
import configuration_export as export
from unittest import mock

OID='11111111-1111-4111-8111-111111111111'
PARENT='22222222-2222-4222-8222-222222222222'
FEATURE='33333333-3333-4333-8333-333333333333'
UNKNOWN='55555555-5555-4555-8555-555555555555'
Q='{http://v8.1c.ru/8.3/MDClasses}'


class CompiledGraphTests(unittest.TestCase):
    def setUp(self):
        self.fixtures=json.loads(Path(__file__).with_name('fixtures').joinpath('compiled_owners.json').read_text(encoding='utf-8'))

    def records(self,kind='Catalog'):
        node=E.fromstring('<'+kind+' xmlns="'+Q[1:-1]+'" uuid="'+OID+'"><ChildObjects><Attribute uuid="'+FEATURE+'"/></ChildObjects></'+kind+'>')
        owner=dict(id=OID,kind=kind,parent_id=PARENT,name='TestDocument',node=node)
        parent=dict(id=PARENT,kind='Configuration',parent_id=s.ZERO,name='Cfg',node=E.Element(Q+'Configuration',uuid=PARENT))
        return owner,{OID:owner,PARENT:parent},{OID:self.fixtures[kind]['before'].encode()}

    def test_same_reader_proves_four_different_native_layouts(self):
        for kind in ('Catalog','Document','DataProcessor','Report'):
            with self.subTest(kind=kind):
                record,inventory,image=self.records(kind);facts=graph.read(record,inventory,image)
                self.assertEqual(facts.features,(FEATURE,));self.assertEqual(facts.class_id,metadata_structure.profile(kind)['class_id'])
                self.assertEqual(facts.parent_id,PARENT);self.assertEqual(facts.name,'TestDocument')

    def test_native_class_constants_and_other_uuids_do_not_become_features(self):
        record,inventory,image=self.records()
        body=s.Parser(image[OID].decode()).documents();body.append([s.atom(UNKNOWN)])
        image[OID]=s.native_body_bytes(body)
        facts=graph.read(record,inventory,image)
        self.assertEqual(facts.features,(FEATURE,));self.assertNotIn(UNKNOWN,facts.features)
        record['node'].find(Q+'ChildObjects/'+Q+'Attribute').set('uuid',UNKNOWN)
        with self.assertRaisesRegex(ValueError,'common identity'):graph.read(record,inventory,image)

    def test_generated_ids_require_actual_native_presence(self):
        record,inventory,image=self.records();info=E.SubElement(record['node'],Q+'InternalInfo');generated=E.SubElement(info,graph.XR+'GeneratedType')
        field=E.SubElement(generated,graph.XR+'TypeId');field.text=self.fixtures['Catalog']['generated']
        self.assertEqual(graph.read(record,inventory,image).generated,frozenset((field.text,)))
        field.text=UNKNOWN
        with self.assertRaisesRegex(ValueError,'absent from compiled CF'):graph.read(record,inventory,image)

    def test_duplicate_features_wrong_name_and_undeclared_child_mismatch_fail(self):
        record,inventory,image=self.records();record['name']='Other'
        with self.assertRaisesRegex(ValueError,'name differs'):graph.read(record,inventory,image)
        record['name']='TestDocument';E.SubElement(record['node'].find(Q+'ChildObjects'),Q+'Attribute',uuid=FEATURE)
        with self.assertRaisesRegex(ValueError,'Duplicate'):graph.read(record,inventory,image)
        record,inventory,image=self.records();inventory[UNKNOWN]=dict(id=UNKNOWN,kind='Form',parent_id=OID,name='MissingForm',node=E.Element(Q+'Form',uuid=UNKNOWN))
        with self.assertRaisesRegex(ValueError,'stored children differ'):graph.read(record,inventory,image)

    def typed_index(self,kind='Report',alias='ReportObject.TestDocument'):
        record,inventory,image=self.records(kind)
        generated=E.SubElement(E.SubElement(record['node'],Q+'InternalInfo'),graph.XR+'GeneratedType',name=alias)
        E.SubElement(generated,graph.XR+'TypeId').text=self.fixtures[kind]['generated']
        return graph.TypeIndex(inventory,image),record,inventory,image

    def test_type_names_come_from_verified_declarations_instead_of_a_class_list(self):
        index,record,inventory,image=self.typed_index()
        value='cfg:ReportObject.TestDocument';native=self.fixtures['Report']['generated']
        self.assertEqual(index.reference(value),(native,OID))
        xml='<Type xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:v8="http://v8.1c.ru/8.1/data/core"><v8:Type>'+value+'</v8:Type></Type>'
        self.assertEqual(metadata_type_references.resolve(xml,dict(_compiled_types=index)),{value:native})
        form='<Form xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:v8="http://v8.1c.ru/8.1/data/core"><Attributes><Attribute name="Other" id="1"><Type><v8:Type>'+value+'</v8:Type></Type></Attribute></Attributes></Form>'
        self.assertEqual(form_attribute_types.resolve(form,dict(_compiled_types=index)),{value:native})
        self.assertEqual(index.object_ids_required({value}),{OID})
        with self.assertRaisesRegex(ValueError,'Unresolved compiled metadata type'):index.reference('cfg:ReportObject.Missing')

    def test_generated_ownership_is_proven_before_source_dependencies_are_used(self):
        index,record,inventory,image=self.typed_index()
        value=self.fixtures['Report']['generated']
        self.assertEqual(index.owner_for_generated(value),OID)
        self.assertIsNone(index.owner_for_generated(UNKNOWN))
        image[OID]=image[OID].replace(value.encode(),UNKNOWN.encode())
        another=graph.TypeIndex(inventory,image)
        with self.assertRaisesRegex(ValueError,'absent from compiled CF'):another.owner_for_generated(value)

    def test_ambiguous_names_across_objects_are_rejected(self):
        index,record,inventory,image=self.typed_index()
        other=E.fromstring(E.tostring(record['node']));other.set('uuid',UNKNOWN);other.find(Q+'ChildObjects/'+Q+'Attribute').set('uuid','77777777-7777-4777-8777-777777777777')
        generated=other.find('.//'+graph.XR+'TypeId');generated.text='66666666-6666-4666-8666-666666666666'
        inventory[UNKNOWN]=dict(record,id=UNKNOWN,node=other)
        with self.assertRaisesRegex(ValueError,'Ambiguous generated type name'):graph.TypeIndex(inventory,image)

    def test_group_dependency_is_a_verified_root_feature_instead_of_the_root_object(self):
        record,inventory,image=self.records()
        root=inventory[PARENT];node=E.SubElement(root['node'],graph.XR+'ContainedObject')
        E.SubElement(node,graph.XR+'ClassId').text=metadata_identifiers.group_id('Main')
        E.SubElement(node,graph.XR+'ObjectId').text=UNKNOWN
        index=graph.TypeIndex(inventory,image)
        with mock.patch.object(index,'facts') as prove:
            self.assertEqual(index.reference('cfg:CatalogObject'),(metadata_type_sets.profile()['cfg:CatalogObject'],UNKNOWN))
            prove.assert_called_once_with(PARENT)
        self.assertNotEqual(UNKNOWN,PARENT)

    def missing_class_inventory(self):
        parent=dict(id=PARENT,kind='CalculationRegister',parent_id=s.ZERO,name='Register',node=E.Element(Q+'CalculationRegister',uuid=PARENT))
        child=dict(id=OID,kind='Recalculation',parent_id=PARENT,name='Recalc',node=E.Element(Q+'Recalculation',uuid=OID))
        body=s.Parser('{'+UNKNOWN+',1,'+OID+'}').documents()
        return {PARENT:parent,OID:child},{PARENT:s.native_body_bytes(body)}

    def test_missing_schema_class_is_bound_to_unique_native_member_collection(self):
        inventory,image=self.missing_class_inventory()
        with self.assertRaisesRegex(ValueError,'Missing stored metadata class'):export.class_id(inventory[OID],inventory)
        index=graph.TypeIndex(inventory,image)
        self.assertEqual(export.class_id(inventory[OID],index.inventory),UNKNOWN)
        separate=dict(inventory[OID]);separate.pop('_class_id')
        self.assertEqual(export.class_id(separate,index.inventory),UNKNOWN)
        groups=graph.native_object_reader.stored_collections(s.Parser(image[PARENT].decode('utf-8-sig')).documents(),'CalculationRegister',(UNKNOWN,))
        self.assertEqual(groups,{UNKNOWN:[OID]})

    def test_class_inference_rejects_empty_missing_ambiguous_and_malformed_rows(self):
        with self.assertRaisesRegex(ValueError,'empty'):graph.collection_class([],[])
        rows=['{'+UNKNOWN+',0,'+OID+'}', '{'+UNKNOWN+',+1,'+OID+'}',
              '{"'+UNKNOWN+'",1,'+OID+'}', '{'+UNKNOWN+',1,'+FEATURE+'}',
              '{'+UNKNOWN+',2,'+OID+','+OID+'}',
              '{'+UNKNOWN+',1,'+OID+'},{'+FEATURE+',1,'+OID+'}']
        for text in rows:
            with self.subTest(text=text),self.assertRaisesRegex(ValueError,'Missing or ambiguous'):
                graph.collection_class(s.Parser(text).documents(),[OID])

    def test_class_binding_rejects_owned_identity_and_conflicting_previous_binding(self):
        inventory,image=self.missing_class_inventory();image[PARENT]=image[PARENT].replace(UNKNOWN.encode(),PARENT.encode())
        with self.assertRaisesRegex(ValueError,'overlaps an owned identity'):graph.TypeIndex(inventory,image)
        inventory,image=self.missing_class_inventory();inventory[OID]['_class_id']=FEATURE
        with self.assertRaisesRegex(ValueError,'Conflicting native class binding'):graph.TypeIndex(inventory,image)

    def test_inferred_class_is_used_by_complete_parent_and_child_identity_checks(self):
        inventory,image=self.missing_class_inventory()
        image[PARENT]=s.native_body_bytes(s.Parser('{{3,{1,0,'+PARENT+'},"Register"},{'+UNKNOWN+',1,'+OID+'}}').documents())
        image[OID]=s.native_body_bytes(s.Parser('{3,{1,0,'+OID+'},"Recalc"}').documents())
        index=graph.TypeIndex(inventory,image)
        self.assertEqual(index.facts(PARENT).children,{UNKNOWN:[OID]})
        self.assertEqual(index.facts(OID).class_id,UNKNOWN)
        self.assertEqual(index.facts(OID).parent_id,PARENT)

    def test_source_class_hint_cannot_override_known_schema_class(self):
        record,inventory,image=self.records()
        with self.assertRaisesRegex(ValueError,'differs from schema'):export.class_id(record,inventory,UNKNOWN)
        inventory,image=self.missing_class_inventory()
        self.assertEqual(export.class_id(inventory[OID],inventory,UNKNOWN),UNKNOWN)
        self.assertNotIn('_class_id',inventory[OID])
        graph.TypeIndex(inventory,image)
        with self.assertRaisesRegex(ValueError,'differs from schema/source'):export.class_id(inventory[OID],inventory,FEATURE)


if __name__=='__main__':unittest.main()
