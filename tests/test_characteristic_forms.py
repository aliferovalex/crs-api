"""Characteristic main form bindings follow independently compiled forms."""
import copy,json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
import test_document_serializer
import managed_form_xml as forms,managed_form_operations as operations,native_metadata as s
from test_defined_type_forms import signature
KIND='ChartOfCharacteristicType'


class CharacteristicFormTests(unittest.TestCase):
    def samples(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('characteristic_forms_851.json').read_text(encoding='utf-8'))['forms']

    def test_all_whole_forms_match_native_and_create_from_empty_template(self):
        for row in self.samples():
            with self.subTest(case=row['label']):
                owner=s.Parser(row['owner_body']).documents()[0];paths=forms.object_paths(owner,KIND);raw=forms.convert(row['interface'].encode('utf-8-sig'),row['xml'],paths=paths,object_name=row['owner'],kind=KIND)
                self.assertEqual(signature(s.Parser(raw.decode('utf-8-sig')).documents()),signature(s.Parser(row['interface']).documents()))
                name=E.fromstring(row['definition'])[0].findtext('{http://v8.1c.ru/8.3/MDClasses}Properties/{http://v8.1c.ru/8.3/MDClasses}Name')
                _,_,created=operations.create_native(KIND,name,'8.5.1.1529',owner,row['definition'],row['xml'],'')
                # XML import and fresh creation can encode implicit defaults
                # differently. This separate variant was accepted by Designer,
                # exported to the same complete XML, and compared field by field.
                self.assertEqual(signature(s.Parser(created.decode('utf-8-sig')).documents()),signature(s.Parser(row['creation_interface']).documents()))

    def test_native_loaded_creation_variants_export_the_same_complete_xml(self):
        from metadata_common_xml import canonical
        for row in self.samples():
            with self.subTest(case=row['label']):
                self.assertEqual(canonical(E.fromstring(row['creation_xml'])),canonical(E.fromstring(row['xml'])))

    def test_main_type_uses_xml_alias_and_owner_generated_identity(self):
        for row in self.samples():
            owner=s.Parser(row['owner_body']).documents()[0];paths=forms.object_paths(owner,KIND)
            self.assertEqual(paths.main_types,{'cfg:ChartOfCharacteristicTypesObject.'+row['owner']:s.val(owner[1][1])})
            for key,code in [('Code',-8),('Description',-9),('DeletionMark',-4)]:self.assertEqual(s.render(paths['Object.'+key]),'{2,{1},{%d}}'%code)
            with self.assertRaisesRegex(ValueError,'does not match'):forms.convert(row['interface'].encode('utf-8-sig'),row['xml'].replace('cfg:ChartOfCharacteristicTypesObject.','cfg:ChartOfCharacteristicTypeObject.'),paths=paths,object_name=row['owner'],kind=KIND)

    def test_scalar_and_tabular_paths_resolve_actual_instance_ids(self):
        row=next(r for r in self.samples() if r['label']=='Mixed');owner=s.Parser(row['owner_body']).documents()[0];paths=forms.object_paths(owner,KIND);field=owner[3][2];table=owner[5][2];aid=s.val(field[0][1][1][1][1][2]);tid=s.val(table[0][1][5][1][1][2]);column=table[2][2];cid=s.val(column[0][1][1][1][1][2])
        self.assertEqual(s.render(paths['Object.Flag']),'{2,{1},{0,%s}}'%aid);self.assertEqual(paths.types['Object.Flag'],'B');self.assertIn('Object.Rows',paths.tables)
        self.assertEqual(s.render(paths['Object.Rows.Text']),'{3,{1},{0,%s},{0,%s}}'%(tid,cid));self.assertEqual(paths.types['Object.Rows.Amount'],'N')

    def test_missing_and_ambiguous_field_paths_are_rejected(self):
        row=next(r for r in self.samples() if r['label']=='AttributeString');owner=s.Parser(row['owner_body']).documents()[0];paths=forms.object_paths(owner,KIND)
        with self.assertRaises(ValueError):forms.convert(row['interface'].encode('utf-8-sig'),row['xml'].replace('Object.Value','Object.Missing'),paths=paths,object_name=row['owner'],kind=KIND)
        duplicate=copy.deepcopy(owner);duplicate[3].append(copy.deepcopy(duplicate[3][2]));duplicate[3][1]=s.atom(2)
        with self.assertRaisesRegex(ValueError,'Duplicate'):forms.object_paths(duplicate,KIND)

    def test_item_form_usage_is_read_from_the_owner_profile(self):
        row=self.samples()[0];owner=s.Parser(row['owner_body']).documents()[0];paths=forms.object_paths(owner,KIND)
        for value in ('Folders','FoldersAndItems'):
            root=E.fromstring(row['xml']);root.find(forms.Q+'UseForFoldersAndItems').text=value
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'item/folder usage'):forms.convert(row['interface'].encode('utf-8-sig'),E.tostring(root,encoding='unicode'),paths=paths,object_name=row['owner'],kind=KIND)

    def test_custom_table_search_links_are_retargeted_without_changing_user_text(self):
        row=next(r for r in self.samples() if r['label']=='CustomTable');owner=s.Parser(row['owner_body']).documents()[0];raw=operations.create_native(KIND,'CustomTable','8.5.1.1529',owner,row['definition'],row['xml'],'')[2];values=[];links=[]
        def collect(node):
            if not isinstance(node,list):values.append(s.val(node));return
            if len(node)==25 and isinstance(node[0],s.Atom) and s.val(node[0])=='6':links.append(s.val(node[24]))
            for child in node:collect(child)
        collect(s.Parser(raw.decode('utf-8-sig')).documents());self.assertIn('RowsTableСтрокаПоиска literal',values);self.assertIn('EntriesSearch',links);self.assertIn('EntriesControl',links);self.assertNotIn('RowsTableСтрокаПоиска',links)
