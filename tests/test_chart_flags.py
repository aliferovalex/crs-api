"""Accounting flag collections reuse the common typed inline XML codec."""
import copy,json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
import test_document_serializer
import metadata_object_xml as objects,native_metadata as s


class ChartFlagTests(unittest.TestCase):
    def samples(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('chart_flags_851.json').read_text(encoding='utf-8'))['samples']

    def test_complete_native_bodies_and_inverse_xml_match(self):
        for row in self.samples():
            with self.subTest(case=row['label']):
                raw=objects.create(row['xml'],'8.5.1.1529','ChartOfAccounts')[2];self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(row['body']).documents()))
                top=objects.export(s.Parser(row['body']).documents()[0],{},'8.5.1.1529','ChartOfAccounts');self.assertEqual(objects.create(E.tostring(top,encoding='unicode'),'8.5.1.1529','ChartOfAccounts')[2],raw)

    def test_changes_rename_comment_reorder_and_remove_full_collections(self):
        row=next(row for row in self.samples() if row['label']=='TwoAccounting');source=s.Parser(row['body']).documents()[0];root=E.fromstring(row['xml']);children=root[0].find(objects.Q+'ChildObjects');first,second=list(children);children.remove(first);children.append(first);first.find(objects.Q+'Properties/'+objects.Q+'Name').text='RenamedFlag';first.find(objects.Q+'Properties/'+objects.Q+'Comment').text='Changed flag'
        raw,features=objects.change(E.tostring(root,encoding='unicode'),'8.5.1.1529','ChartOfAccounts',source);body=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        self.assertEqual([s.val(entry[0][1][1][1][1][2]) for entry in body[8][2:]],[second.get('uuid'),first.get('uuid')]);self.assertEqual(s.val(body[8][3][0][1][1][1][2]),'RenamedFlag');self.assertEqual(set(features),{first.get('uuid'),second.get('uuid')})
        children.remove(first);raw,features=objects.change(E.tostring(root,encoding='unicode'),'8.5.1.1529','ChartOfAccounts',body);self.assertEqual(features,[second.get('uuid')])

    def test_existing_flag_uuid_cannot_move_between_collections(self):
        row=next(row for row in self.samples() if row['label']=='Both');source=s.Parser(row['body']).documents()[0];root=E.fromstring(row['xml']);root[0].find(objects.Q+'ChildObjects')[0].tag=objects.Q+'ExtDimensionAccountingFlag'
        with self.assertRaisesRegex(ValueError,'cannot move between collections'):objects.change(E.tostring(root,encoding='unicode'),'8.5.1.1529','ChartOfAccounts',source)

    def test_duplicate_ids_names_and_out_of_schema_properties_reject(self):
        row=next(row for row in self.samples() if row['label']=='Accounting');root=E.fromstring(row['xml']);children=root[0].find(objects.Q+'ChildObjects');children.append(copy.deepcopy(children[0]))
        with self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','ChartOfAccounts')
        root=E.fromstring(row['xml']);props=root[0].find(objects.Q+'ChildObjects')[0].find(objects.Q+'Properties');E.SubElement(props,objects.Q+'Indexing').text='Index'
        with self.assertRaisesRegex(ValueError,'outside its owner profile'):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','ChartOfAccounts')

    def test_unbounded_type_patterns_are_compact_and_not_guessed_lengths(self):
        import type_description_xml as types
        for source in ('{"Pattern",{"S"}}','{"Pattern",{"N"}}'):
            pattern=s.Parser(source).documents()[0];self.assertEqual(s.render(types.read_metadata(types.export_metadata(pattern,objects.Q+'Type'))),source)
