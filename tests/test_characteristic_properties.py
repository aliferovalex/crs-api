"""Whole characteristic-plan XML follows independent Configurator evidence."""
import copy,json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
import test_document_serializer
import metadata_object_xml as objects,native_metadata as s,type_description_xml as types,xml_namespaces
KIND='ChartOfCharacteristicType'


class CharacteristicPropertyTests(unittest.TestCase):
    def samples(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('characteristic_properties_851.json').read_text(encoding='utf-8'))['samples']
    def references(self):
        return {'cfg:'+n.get('name'):n[0].text for row in self.samples() for n in E.fromstring(row['xml'])[0].find(objects.Q+'InternalInfo') if n.get('category') in ('Ref','Characteristic')}

    def test_complete_native_bodies_and_inverse_xml_match_all_samples(self):
        for row in self.samples():
            with self.subTest(case=row['label']):
                raw=objects.create(row['xml'],'8.5.1.1529',KIND,type_references=self.references())[2]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(row['body']).documents()))
                exported=objects.export(s.Parser(row['body']).documents()[0],{},'8.5.1.1529',KIND,type_references=self.references())
                self.assertEqual(exported[0].tag,objects.Q+'ChartOfCharacteristicTypes')
                self.assertEqual(objects.create(E.tostring(exported,encoding='unicode'),'8.5.1.1529',KIND,type_references=self.references())[2],raw)

    def test_change_complete_properties_and_types_retains_all_generated_identities(self):
        rows=self.samples();source=s.Parser(rows[0]['body']).documents()[0];layout=objects.profiles.layout(KIND)
        for row in rows[1:]:
            root=E.fromstring(row['xml']);root[0].set('uuid',rows[0]['id']);root[0].find(objects.Q+'Properties/'+objects.Q+'Name').text=rows[0]['name'];root[0].find(objects.Q+'Properties/'+objects.Q+'InputByString').clear()
            # Keep the source search fields, expressed with the XML alias.
            root[0].find(objects.Q+'Properties/'+objects.Q+'InputByString')[:]=copy.deepcopy(E.fromstring(rows[0]['xml'])[0].find(objects.Q+'Properties/'+objects.Q+'InputByString')[:])
            for old,new in zip(root[0].find(objects.Q+'InternalInfo'),E.fromstring(rows[0]['xml'])[0].find(objects.Q+'InternalInfo')):old.attrib=dict(new.attrib);old[:]=copy.deepcopy(list(new))
            for node in root.iter('{'+xml_namespaces.READABLE+'}Field'):
                node.text=node.text.replace('ChartOfCharacteristicTypes.'+row['name']+'.','ChartOfCharacteristicTypes.'+rows[0]['name']+'.')
            raw,_=objects.change(xml_namespaces.render(root,row['xml']),'8.5.1.1529',KIND,source,type_references=self.references())
            actual=s.Parser(raw.decode('utf-8-sig')).documents()[0];expected=s.Parser(row['body']).documents()[0]
            expected[1][13][1]=copy.deepcopy(source[1][13][1])
            for slot in layout['generated_slots']:expected[1][slot]=copy.deepcopy(source[1][slot])
            self.assertEqual(s.render(actual),s.render(expected),row['label'])

    def test_missing_internal_info_allocates_all_six_categories_with_correct_prefixes(self):
        row=self.samples()[0];root=E.fromstring(row['xml']);root[0].remove(root[0].find(objects.Q+'InternalInfo'))
        _,_,raw,generated=objects.create(xml_namespaces.render(root,row['xml']),'8.5.1.1529',KIND)
        self.assertEqual(len(set(generated)),12)
        exported=objects.export(s.Parser(raw.decode('utf-8-sig')).documents()[0],{},'8.5.1.1529',KIND)
        self.assertEqual([n.get('name') for n in exported[0].find(objects.Q+'InternalInfo')],['ChartOfCharacteristicTypes'+cat+'.'+row['name'] if cat!='Characteristic' else 'Characteristic.'+row['name'] for cat in ('Object','Ref','Selection','List','Characteristic','Manager')])
        self.assertEqual(objects.profiles.reference_types(KIND),{'ChartOfCharacteristicTypesRef':'Ref','Characteristic':'Characteristic'})

    def test_unknown_property_values_and_native_class_spelling_reject(self):
        row=self.samples()[0]
        for key,value in [('CodeLength','-1'),('DescriptionLength','0'),('Hierarchical','unknown'),('CodeSeries','WholeCatalog'),('CharacteristicExtValues','Catalog.Missing')]:
            root=E.fromstring(row['xml']);root[0].find(objects.Q+'Properties/'+objects.Q+key).text=value
            with self.subTest(property=key),self.assertRaises(ValueError):objects.create(xml_namespaces.render(root,row['xml']),'8.5.1.1529',KIND)
        with self.assertRaises(ValueError):objects.create(row['xml'].replace('ChartOfCharacteristicTypes','ChartOfCharacteristicType'),'8.5.1.1529',KIND)

    def test_characteristic_is_a_type_set_and_ref_is_a_scalar_reference(self):
        import metadata_type_references,metadata_type_sets
        for label,value,category in [('Reference','cfg:ChartOfCharacteristicTypesRef.ProbeDefault','Ref'),('CharacteristicSet','cfg:Characteristic.ProbeString','Characteristic')]:
            row=next(r for r in self.samples() if r['label']==label)
            self.assertEqual(metadata_type_references.reference_definition(value),(KIND,value.rsplit('.',1)[1],category))
            self.assertEqual(metadata_type_sets.is_set(value),category=='Characteristic')
            root=E.fromstring(row['xml']);node=root[0].find(objects.Q+'Properties/'+objects.Q+'Type')[0];node.tag=types.Q+('Type' if category=='Characteristic' else 'TypeSet')
            with self.assertRaisesRegex(ValueError,'TypeSet requires'):objects.create(xml_namespaces.render(root,row['xml']),'8.5.1.1529',KIND,type_references=self.references())

    def test_native_type_dependencies_refer_to_metadata_owners_not_generated_ids(self):
        rows=self.samples()
        for row in rows:
            expected={}
            for node in E.fromstring(row['xml']).find('.//'+objects.Q+'Type'):
                if node.tag in (types.Q+'Type',types.Q+'TypeSet') and node.text.startswith('cfg:'):
                    target=next(r for r in rows if r['name']==node.text.rsplit('.',1)[1]);expected[target['id']]=0
                    self.assertNotIn(self.references()[node.text],row['native_relations'])
            self.assertEqual({key:value for key,value in row['native_relations'].items() if value==0},expected)

    def test_field_lists_use_xml_alias_and_whole_target_order(self):
        row=self.samples()[0];source=s.Parser(row['body']).documents()[0];root=E.fromstring(row['xml']);props=root[0].find(objects.Q+'Properties');search=props.find(objects.Q+'InputByString');search[:]=list(reversed(list(search)))
        raw,_=objects.change(xml_namespaces.render(root,row['xml']),'8.5.1.1529',KIND,source);body=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        self.assertEqual([s.val(n[2][0]) for n in body[1][33][1][2:]],['-8','-9'])
        search.clear();raw,_=objects.change(xml_namespaces.render(root,row['xml']),'8.5.1.1529',KIND,source);self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()[0][1][33][1]),'{0,0}')
        E.SubElement(search,'{'+xml_namespaces.READABLE+'}Field').text='ChartOfCharacteristicType.'+row['name']+'.StandardAttribute.Code'
        with self.assertRaisesRegex(ValueError,'foreign'):objects.create(xml_namespaces.render(root,row['xml']),'8.5.1.1529',KIND)

    def test_both_module_streams_use_shared_text_containers(self):
        import base64
        from commonmodule_serializer import module_container
        from test_commonmodule_serializer import container_members
        case=json.loads(Path(__file__).with_name('fixtures').joinpath('characteristic_modules_851.json').read_text(encoding='utf-8'))
        self.assertEqual(objects.profiles.module_files(KIND),case['modules'])
        for name,text in case['sources'].items():
            self.assertEqual(container_members(module_container(text)),container_members(base64.b64decode(case['native_streams'][name])))
