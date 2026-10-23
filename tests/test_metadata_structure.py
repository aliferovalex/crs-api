"""Schema availability is distinct from verified native write coverage."""
import importlib.util, sys, unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(next((root/'src').rglob('metadata_structure.py')).parent))
import metadata_structure as structure
spec=importlib.util.spec_from_file_location('schema_map_builder',root/'tools'/'build_metadata_structure.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)


class MetadataStructureTests(unittest.TestCase):
    def test_complete_extracted_map_and_references(self):
        classes=structure.classes();self.assertEqual(len(classes),75)
        self.assertEqual(sum(len(v['collections']) for v in classes.values()),173)
        for owner in classes.values():
            for collection in owner['collections']:
                self.assertIn(collection['item_type'],classes)
                self.assertIn(collection['native']['status'],('unmapped','verified_profile','snapshot_collection'))

    def test_storage_and_native_paths_are_owner_specific(self):
        catalog={c['xml_name']:c for c in structure.profile('Catalog')['collections']}
        self.assertEqual(catalog['Form']['storage'],'stored_name');self.assertEqual(catalog['Form']['native']['path'],[7])
        self.assertEqual(catalog['Attribute']['storage'],'inline_xml');self.assertEqual(catalog['Attribute']['native']['path'],[6])
        self.assertEqual(catalog['Command']['native']['status'],'verified_profile')
        self.assertEqual(catalog['Command']['native']['path'],[4])
        self.assertEqual(catalog['Command']['native']['serializer'],'inline_metadata_xml')
        for kind,slot in [('Enum',5),('InformationRegister',8),('AccumulationRegister',4),('AccountingRegister',6)]:
            command=next(row for row in structure.profile(kind)['collections'] if row['xml_name']=='Command')
            self.assertEqual(command['native']['status'],'verified_profile');self.assertEqual(command['native']['path'],[slot])
        tabular=structure.profile('TabularSection')['collections'][0]['owner_native_profiles']
        self.assertEqual(tabular['Catalog']['collection_id'],tabular['Document']['collection_id'])
        document={c['xml_name']:c for c in structure.profile('Document')['collections']}
        self.assertNotEqual(catalog['TabularSection']['native']['collection_id'],document['TabularSection']['native']['collection_id'])

    def test_unimplemented_parents_are_not_activated_by_the_schema(self):
        register={c['xml_name']:c for c in structure.profile('InformationRegister')['collections']}
        self.assertEqual(register['Form']['native']['status'],'snapshot_collection')
        self.assertIsNone(register['Form']['native']['path'])
        self.assertIn('InformationRegister',structure.automatic_owners())
        self.assertNotIn('Subsystem',structure.automatic_owners())
        self.assertIn(('Subsystem','Subsystem','stored_name'),structure.parents_of('Subsystem'))
        self.assertIn('Catalog',structure.automatic_owners())

    def test_aliases_and_returned_models_are_isolated(self):
        self.assertEqual(structure.profile('ChartOfCharacteristicTypes'),structure.profile('ChartOfCharacteristicType'))
        record=structure.profile('Catalog');record['collections'].clear()
        self.assertEqual(len(structure.profile('Catalog')['collections']),5)

    def test_characteristic_collections_match_verified_owner_specific_slots(self):
        rules={r['xml_name']:r['native'] for r in structure.profile('ChartOfCharacteristicType')['collections']}
        for name,slot in [('Attribute',3),('TabularSection',5),('Command',6)]:
            self.assertEqual(rules[name]['path'],[slot]);self.assertEqual(rules[name]['status'],'verified_profile');self.assertEqual(rules[name]['format'],'collection_uuid,count,inline_entries')
        self.assertIn('ChartOfCharacteristicType',structure.profile('TabularSection')['collections'][0]['owner_native_profiles'])

    def test_schema_extraction_retains_empty_and_recursive_collections(self):
        text=b'''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="http://v8.1c.ru/8.3/MDClasses">
          <xs:complexType name="MetaDataObject"><xs:choice><xs:element name="Owner" type="tns:Owner"/></xs:choice></xs:complexType>
          <xs:complexType name="Owner"><xs:sequence><xs:element name="Properties" type="tns:P"/><xs:element name="ChildObjects" type="tns:C"/></xs:sequence></xs:complexType>
          <xs:complexType name="P"><xs:sequence><xs:element name="Name" type="xs:string"/></xs:sequence></xs:complexType>
          <xs:complexType name="C"><xs:sequence><xs:element name="Owner" type="xs:string" minOccurs="0" maxOccurs="unbounded"/></xs:sequence></xs:complexType>
        </xs:schema>'''
        classes=builder.schema_classes(text);collection=classes['Owner']['collections'][0]
        self.assertEqual(collection['item_type'],'Owner');self.assertEqual(collection['storage'],'stored_name')
        self.assertTrue(classes['Owner']['exported'])
        with self.assertRaises(ValueError):builder.schema_classes(b'<!DOCTYPE x>'+text)


if __name__=='__main__':unittest.main()
