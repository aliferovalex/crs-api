"""Characteristic children share typed field, table and command codecs."""
import copy,json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
import test_document_serializer
import metadata_object_xml as objects,native_metadata as s,inline_object_xml as inline,tabular_section_xml as tables,xml_namespaces
KIND='ChartOfCharacteristicType'


class CharacteristicChildrenTests(unittest.TestCase):
    def samples(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('characteristic_children_851.json').read_text(encoding='utf-8'))['samples']
    def references(self):return {'cfg:'+node.get('name'):node[0].text for row in self.samples() for node in E.fromstring(row['xml'])[0].find(objects.Q+'InternalInfo') if node.get('category') in ('Ref','Characteristic')}

    def test_complete_native_bodies_and_inverse_xml(self):
        for row in self.samples():
            with self.subTest(case=row['label']):
                raw=objects.create(row['xml'],'8.5.1.1529',KIND,type_references=self.references())[2];body=s.Parser(row['body']).documents()[0]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()[0]),s.render(body))
                root=objects.export(body,{},'8.5.1.1529',KIND,type_references=self.references())
                self.assertEqual(objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529',KIND,type_references=self.references())[2],raw)

    def test_changes_remove_whole_collections_without_changing_owner_ids(self):
        row=next(r for r in self.samples() if r['label']=='Mixed');source=s.Parser(row['body']).documents()[0];root=E.fromstring(row['xml']);root[0].find(objects.Q+'ChildObjects').clear()
        raw,features=objects.change(xml_namespaces.render(root,row['xml']),'8.5.1.1529',KIND,source);actual=s.Parser(raw.decode('utf-8-sig')).documents()[0];expected=copy.deepcopy(source)
        for slot in (3,5,6):expected[slot]=[expected[slot][0],s.atom(0)]
        self.assertEqual(s.render(actual),s.render(expected));self.assertEqual(features,[])

    def test_tabular_prefix_is_xml_alias_and_generated_ids_are_preserved(self):
        row=next(r for r in self.samples() if r['label']=='TableFields');source=s.Parser(row['body']).documents()[0];root=E.fromstring(row['xml']);section=root.find('.//'+objects.Q+'TabularSection');props=section.find(objects.Q+'Properties');props.find(objects.Q+'Comment').text='Changed complete section';children=section.find(objects.Q+'ChildObjects');children[:]=list(reversed(list(children)))
        raw,_=objects.change(xml_namespaces.render(root,row['xml']),'8.5.1.1529',KIND,source);actual=s.Parser(raw.decode('utf-8-sig')).documents()[0];self.assertEqual(s.render(actual[5][2][0][1][1:5]),s.render(source[5][2][0][1][1:5]));self.assertEqual([s.val(t[0][1][1][1][2]) for t in actual[5][2][2][2:]],['Amount','Text'])
        section.find(objects.Q+'InternalInfo')[0].set('name',section.find(objects.Q+'InternalInfo')[0].get('name').replace('ChartOfCharacteristicTypes','ChartOfCharacteristicType'))
        with self.assertRaisesRegex(ValueError,'generated type'):objects.create(xml_namespaces.render(root,row['xml']),'8.5.1.1529',KIND)

    def test_same_attribute_uuid_cannot_move_into_a_table(self):
        row=next(r for r in self.samples() if r['label']=='Mixed');source=s.Parser(row['body']).documents()[0];root=E.fromstring(row['xml']);children=root[0].find(objects.Q+'ChildObjects');attr=children.find(objects.Q+'Attribute');children.remove(attr);children.find(objects.Q+'TabularSection/'+objects.Q+'ChildObjects').append(attr)
        props=attr.find(objects.Q+'Properties')
        for key in ('FillValue','FillFromFillingValue'):props.remove(props.find(objects.Q+key))
        with self.assertRaisesRegex(ValueError,'cannot move between collections'):objects.change(xml_namespaces.render(root,row['xml']),'8.5.1.1529',KIND,source)

    def test_inline_feature_scope_and_command_streams_use_instance_ids(self):
        import inline_command_xml
        row=next(r for r in self.samples() if r['label']=='Mixed');source=s.Parser(row['body']).documents()[0];layout=objects.profiles.layout(KIND);root=E.fromstring(row['xml']);expected={node.get('uuid') for node in root.iter() if node.tag in {objects.Q+name for name in ('Attribute','TabularSection','Command')}}
        self.assertEqual(set(inline.features(source,layout)),expected);self.assertEqual(set(inline.scopes(source,layout)),expected)
        cid=root.find('.//'+objects.Q+'Command').get('uuid');self.assertEqual(inline_command_xml.streams(source,layout),{cid:cid+'.2'})

    def test_search_and_lock_lists_resolve_actual_attributes_not_commands(self):
        row=next(r for r in self.samples() if r['label']=='FieldLists');source=s.Parser(row['body']).documents()[0];root=E.fromstring(row['xml']);props=root[0].find(objects.Q+'Properties');attr=root.find('.//'+objects.Q+'Attribute');attr.find(objects.Q+'Properties/'+objects.Q+'Indexing').text='Index'
        for key in ('InputByString','DataLockFields'):
            node=props.find(objects.Q+key);node.clear();E.SubElement(node,'{'+xml_namespaces.READABLE+'}Field').text='ChartOfCharacteristicTypes.'+row['name']+'.Attribute.Value'
        raw,_=objects.change(xml_namespaces.render(root,row['xml']),'8.5.1.1529',KIND,source);actual=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        for slot in (33,52):self.assertEqual([s.val(v) for v in actual[1][slot][1][2][2]],['0',attr.get('uuid')])
        objects.export(actual,{},'8.5.1.1529',KIND)

    def test_command_modules_match_independent_native_containers(self):
        import base64
        from commonmodule_serializer import module_container
        from test_commonmodule_serializer import container_members
        for row in self.samples():
            for cid,text in row['command_modules'].items():self.assertEqual(container_members(module_container(text)),container_members(base64.b64decode(row['native_command_streams'][cid+'.2'])))

    def test_search_only_accepts_indexed_single_string_or_number_types(self):
        import type_description_xml as types
        row=next(r for r in self.samples() if r['label']=='FieldLists')
        for pattern in ('{"Pattern",{"B"}}','{"Pattern",{"D"}}','{"Pattern",{"B"},{"S",64,1}}','{"Pattern",{"S",64,1},{"N",15,2,0}}'):
            root=E.fromstring(row['xml']);props=root.find('.//'+objects.Q+'Attribute/'+objects.Q+'Properties');node=props.find(objects.Q+'Type');index=list(props).index(node);props.remove(node);props.insert(index,types.export_metadata(s.Parser(pattern).documents()[0],objects.Q+'Type'))
            with self.subTest(pattern=pattern),self.assertRaisesRegex(ValueError,'field reference'):objects.create(xml_namespaces.render(root,row['xml']),'8.5.1.1529',KIND)

    def test_feature_sets_match_independent_native_repository_descriptors(self):
        for row in self.samples():
            self.assertEqual(set(inline.features(s.Parser(row['body']).documents()[0],objects.profiles.layout(KIND))),set(row['native_features']),row['label'])

    def test_native_export_rejects_a_boolean_search_field_even_when_indexed(self):
        row=next(r for r in self.samples() if r['label']=='FieldLists');body=s.Parser(row['body']).documents()[0];body[3][2][0][1][1][2]=s.Parser('{"Pattern",{"B"}}').documents()[0];body[3][2][0][1][19]=[s.atom('U',True)]
        with self.assertRaisesRegex(ValueError,'Unknown or duplicate native metadata field'):objects.export(body,{},'8.5.1.1529',KIND)
