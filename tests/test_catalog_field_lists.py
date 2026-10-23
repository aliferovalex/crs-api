"""Native complete field lists, owner references and absent standard fields."""
import copy
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree as E
import test_defined_types
import metadata_object_xml as objects
import metadata_targets
import metadata_identifiers as ids
import native_metadata as s
import managed_form_xml as forms
import xml_namespaces


class CatalogFieldListTests(unittest.TestCase):
    def samples(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('catalog_field_lists_851.json').read_text(encoding='utf-8'))['samples']

    def targets(self):return metadata_targets.Index([metadata_targets.Target(row['id'],ids.class_id('Catalog'),s.ZERO,s.ZERO,row['name']) for row in self.samples()])

    def test_all_native_field_lists_owners_and_zero_lengths_roundtrip(self):
        targets=self.targets()
        for case in self.samples():
            with self.subTest(case=case['label']):
                raw=objects.create(case['xml'],'8.5.1.1529','Catalog',objects=targets)[2]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))
                xml=objects.export(s.Parser(case['body']).documents()[0],{},'8.5.1.1529','Catalog',objects=targets)
                self.assertEqual(objects.create(E.tostring(xml,encoding='unicode'),'8.5.1.1529','Catalog',objects=targets)[2],raw)

    def test_whole_changes_preserve_field_order_and_resolve_inline_ids(self):
        samples={row['label']:row for row in self.samples()};before=samples['Default'];source=s.Parser(before['body']).documents()[0]
        for label in ('Reverse','Attribute','Mixed','Empty','Locks','NoCode','NoDescription','SingleOwner','TwoOwners'):
            case=samples[label];root=E.fromstring(case['xml']);root[0].set('uuid',before['id']);root[0].remove(root[0].find(objects.Q+'InternalInfo'));root[0].find(objects.Q+'Properties/'+objects.Q+'Name').text=before['name']
            for node in root.iter():
                if node.text:node.text=node.text.replace('Catalog.'+case['name']+'.','Catalog.'+before['name']+'.')
            root[0].find(objects.Q+'ChildObjects/'+objects.Q+'Attribute').set('uuid',before['attribute_id'])
            with self.subTest(case=label):
                raw,_=objects.change(xml_namespaces.render(root,case['xml']),'8.5.1.1529','Catalog',source,reference_objects=self.targets())
                expected=s.Parser(case['body'].replace(case['id'],before['id']).replace(case['attribute_id'],before['attribute_id'])).documents()[0];common=objects.at(expected,objects.common_path(objects.profiles.layout('Catalog')));common[2]=s.atom(before['name'],True)
                for slot in objects.profiles.layout('Catalog')['generated_slots']:expected[1][slot]=source[1][slot]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()[0]),s.render(expected))

    def test_foreign_missing_and_duplicate_field_references_reject(self):
        case=next(row for row in self.samples() if row['label']=='CodeOnly')
        for value in ('Catalog.Other.StandardAttribute.Code','Catalog.'+case['name']+'.Attribute.Missing'):
            root=E.fromstring(case['xml']);root[0].find(objects.Q+'Properties/'+objects.Q+'InputByString')[0].text=value
            with self.subTest(reference=value),self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','Catalog',objects=self.targets())
        root=E.fromstring(case['xml']);node=root[0].find(objects.Q+'Properties/'+objects.Q+'InputByString');node.append(copy.deepcopy(node[0]))
        with self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','Catalog',objects=self.targets())

    def test_disabled_standard_fields_are_absent_from_form_binding_context(self):
        cases={row['label']:row for row in self.samples()}
        for label,missing in (('NoCode','Object.Code'),('NoDescription','Object.Description')):
            paths=forms.object_paths(s.Parser(cases[label]['body']).documents()[0],'Catalog');self.assertNotIn(missing,paths)
            self.assertIn('Object.SearchKey',paths)

    def test_search_references_require_indexed_attributes_in_both_directions(self):
        case=next(row for row in self.samples() if row['label']=='Attribute')
        root=E.fromstring(case['xml']);attribute=root[0].find(objects.Q+'ChildObjects/'+objects.Q+'Attribute')
        attribute.find(objects.Q+'Properties/'+objects.Q+'Indexing').text='DontIndex'
        with self.assertRaisesRegex(ValueError,'metadata field reference'):
            objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','Catalog',objects=self.targets())
        native=s.Parser(case['body']).documents()[0];native[6][2][0][2]=s.atom(0)
        with self.assertRaisesRegex(ValueError,'native metadata field'):
            objects.export(native,{},'8.5.1.1529','Catalog',objects=self.targets())

    def test_lock_fields_can_reference_an_unindexed_attribute(self):
        case=next(row for row in self.samples() if row['label']=='Locks')
        root=E.fromstring(case['xml']);attribute=root[0].find(objects.Q+'ChildObjects/'+objects.Q+'Attribute')
        self.assertEqual(attribute.findtext(objects.Q+'Properties/'+objects.Q+'Indexing'),'DontIndex')
        raw=objects.create(case['xml'],'8.5.1.1529','Catalog',objects=self.targets())[2]
        native=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.render(native),s.render(s.Parser(case['body']).documents()[0]))
        exported=objects.export(native,{},'8.5.1.1529','Catalog',objects=self.targets())
        fields=exported[0].find(objects.Q+'Properties/'+objects.Q+'DataLockFields')
        self.assertTrue(any(node.text.endswith('.Attribute.SearchKey') for node in fields))

    def test_missing_owner_reference_is_rejected(self):
        case=next(row for row in self.samples() if row['label']=='SingleOwner');root=E.fromstring(case['xml']);root[0].find(objects.Q+'Properties/'+objects.Q+'Owners')[0].text='Catalog.Missing'
        with self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','Catalog',objects=self.targets())

    def test_omitted_search_list_is_checked_against_disabled_template_fields(self):
        case=next(row for row in self.samples() if row['label']=='NoCode');root=E.fromstring(case['xml']);props=root[0].find(objects.Q+'Properties');props.remove(props.find(objects.Q+'InputByString'))
        with self.assertRaisesRegex(ValueError,'Invalid default metadata field list: InputByString'):
            objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','Catalog',objects=self.targets())
