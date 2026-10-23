"""Actual collection rows drive edits; candidate positions cannot authorize them."""
import copy, json, sys, tempfile, unittest, uuid
from xml.etree import ElementTree as E
from pathlib import Path
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('native_collection_editor.py')).parent))
import native_collection_editor as editor
import metadata_context
import xml_namespaces
import native_metadata as s
import automatic_deletion
import delete_object_serializer as deletion
import preparation_plan
import metadata_structure
import object_change_serializer
from test_managed_form_creation import store
from test_delete_object_serializer import fixture
from test_template_deletion import unpack


class NativeCollectionEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native=json.loads(Path(__file__).with_name('fixtures').joinpath('native_register_collections_851.json').read_text(encoding='utf-8'))
        import native_version_fixture
        cls.native['request']['storage']=native_version_fixture.storage(metadata_context.context_objects(cls.native['request']['context']))

    def test_native_register_form_removal_preserves_template_and_opaque_fields(self):
        r=self.native['request'];objects=metadata_context.context_objects(r['context']);m=objects[r['parent_id']][0]
        source=s.Parser(self.native['owner_before']).documents()[0]
        target=editor.edit(source,'InformationRegister',m,objects,r['removed_ids'])
        expected=copy.deepcopy(source);expected[5]=[source[5][0],s.atom(1),source[5][3]]
        self.assertEqual(s.render(target),s.render(expected));self.assertEqual(s.render(source[6]),s.render(target[6]))
        self.assertEqual(s.val(target[5][2]),self.native['remaining_form_id'])
        self.assertEqual(s.render(source[7]),s.render(target[7]))

    def test_raw_editor_changes_only_the_row_span(self):
        r=self.native['request'];objects=metadata_context.context_objects(r['context']);m=objects[r['parent_id']][0]
        text=self.native['owner_before'].replace(',{',' ,\r\n {');source=s.Parser(text).documents()[0];row=source[5]
        raw=b'\xef\xbb\xbf'+text.encode('utf-8');result=editor.edit_raw(raw,'InformationRegister',m,objects,r['removed_ids'])
        expected=text[:row.start]+s.render([row[0],s.atom(1),row[3]])+text[row.end:]
        self.assertEqual(result,b'\xef\xbb\xbf'+expected.encode('utf-8'))

    def test_register_template_removal_preserves_both_forms(self):
        r=self.native['request'];objects=metadata_context.context_objects(r['context']);m=objects[r['parent_id']][0]
        source=s.Parser(self.native['owner_before']).documents()[0]
        target=editor.edit(source,'InformationRegister',m,objects,[self.native['template_id']])
        expected=copy.deepcopy(source);expected[6]=[source[6][0],s.atom(0)]
        self.assertEqual(s.render(target),s.render(expected))
        self.assertEqual(s.render(target[5]),s.render(source[5]))

    def test_packet_matches_native_owner_with_recorded_default_normalization(self):
        result=automatic_deletion.serialize(copy.deepcopy(self.native['request']));_,_,body=unpack(result)
        expected=s.Parser(self.native['owner_after']).documents()[0]
        # This early witness was built with two noncanonical defaults. Its
        # native-load comparison recorded precisely these normalization paths.
        self.assertEqual(self.native['native_normalization_paths'],[[1,23],[7,2,0,1,19]])
        expected[1][23]=s.atom(0);expected[7][2][0][1][19]=[s.atom('U',True)]
        self.assertEqual(s.render(s.Parser(body.decode('utf-8-sig')).documents()),s.render([expected]))
        self.assertEqual(result['removed_ids'],self.native['request']['removed_ids'])

    def test_explicit_register_form_and_template_use_the_same_packet_builder(self):
        for kind,oid in [('InformationRegisterForm',self.native['request']['removed_ids'][0]),('Template',self.native['template_id'])]:
            with self.subTest(kind=kind):
                r=copy.deepcopy(self.native['request']);objects=metadata_context.context_objects(r['context']);m=objects[r['parent_id']][0]
                source=s.Parser(self.native['owner_before']).documents()[0]
                # Use the canonical source representation now produced by the
                # complete XML converter, with matching snapshot bytes.
                source[1][23]=s.atom(0);source[7][2][0][1][19]=[s.atom('U',True)]
                r['snapshot']=store(objects[r['parent_id']],s.native_body_bytes([source]))
                xml=E.fromstring(r['object_xml']);q='{'+xml_namespaces.MD+'}';children=xml[0].find(q+'ChildObjects')
                # Rebuild the authoritative names, omitting only the selected leaf.
                for child in list(children):
                    if child.tag in (q+'Form',q+'Template'):children.remove(child)
                for row in editor.inspect(source,'InformationRegister',m,objects):
                    for child in row['ids']:
                        if child!=oid:E.SubElement(children,q+row['rule']['xml_name']).text=s.val(objects[child][0][9])
                common=editor.at(source,metadata_structure.profile('InformationRegister')['native_identity_path'][:-2])
                xml[0].find(q+'Properties/'+q+'Comment').text=s.val(common[4])
                r.update(object_id=oid,object_xml=E.tostring(xml,encoding='unicode'),object_snapshot=store(objects[oid],b'opaque removed body'),
                         object_original_version=uuid.UUID(s.val(objects[oid][0][7])).bytes_le.hex()+'00000000')
                result=deletion.serialize(r);_,docs,body=unpack(result)
                expected=editor.edit(source,'InformationRegister',m,objects,[oid])
                self.assertEqual(s.render(s.Parser(body.decode('utf-8-sig')).documents()),s.render([expected]))
                self.assertNotIn(oid,[key for key,_ in metadata_context.children(docs[0])])
                self.assertEqual(result['removed_ids'],[oid])
                changed=E.fromstring(r['object_xml'])
                changed[0].find(q+'Properties/'+q+'FullTextSearch').text='Use'
                with self.assertRaisesRegex(ValueError,'must preserve all other'):
                    deletion.serialize(dict(r,object_xml=E.tostring(changed,encoding='unicode')))
                with tempfile.TemporaryDirectory() as directory:
                    path=Path(directory)/'InformationRegister.xml';path.write_text(r['object_xml'],encoding='utf-8')
                    plan=preparation_plan.plan(dict(xml_path=str(path),context=r['context'],options={'operation':'Удаление','object_id':oid}))
                    self.assertEqual(plan['kind'],kind);self.assertEqual(plan['parent_id'],r['parent_id'])

    def test_whole_register_change_retains_all_mapped_forms_and_templates(self):
        r=copy.deepcopy(self.native['request']);objects=metadata_context.context_objects(r['context']);m=objects[r['parent_id']][0]
        source=s.Parser(self.native['owner_before']).documents()[0];q='{'+xml_namespaces.MD+'}'
        xml=E.fromstring(r['object_xml']);children=xml[0].find(q+'ChildObjects')
        for child in list(children):
            if child.tag in (q+'Form',q+'Template'):children.remove(child)
        for row in editor.inspect(source,'InformationRegister',m,objects):
            for oid in row['ids']:E.SubElement(children,q+row['rule']['xml_name']).text=s.val(objects[oid][0][9])
        r.update(object_type='InformationRegister',object_id=r['parent_id'],object_xml=E.tostring(xml,encoding='unicode'))
        result=object_change_serializer.serialize(r,native_content=True);target=s.Parser(result[1].decode('utf-8-sig')).documents()[0]
        for row in editor.inspect(source,'InformationRegister',m,objects):
            self.assertEqual(s.render(editor.at(source,row['path'])),s.render(editor.at(target,row['path'])))
        # A direct ordinary replacement must not silently drop a stored object.
        first=children.find(q+'Form');children.remove(first);r['object_xml']=E.tostring(xml,encoding='unicode')
        with self.assertRaisesRegex(ValueError,'must be preserved'):object_change_serializer.serialize(r,native_content=True)

    def test_class_counts_identity_and_positions_are_checked_before_mutation(self):
        r=self.native['request'];objects=metadata_context.context_objects(r['context']);m=objects[r['parent_id']][0]
        source=s.Parser(self.native['owner_before']).documents()[0];before=s.render(source)
        for mutate in ('count','duplicate','parent','position','owner'):
            body=copy.deepcopy(source);docs=copy.deepcopy(objects);meta=docs[r['parent_id']][0]
            if mutate=='count':body[5][1]=s.atom(100)
            elif mutate=='duplicate':body[5][3]=body[5][2]
            elif mutate=='parent':docs[s.val(body[5][2])][0][3]=s.atom(s.ZERO)
            elif mutate=='position':docs[s.val(body[5][3])][0][10]=docs[s.val(body[5][2])][0][10]
            else:meta[1]=s.atom(s.ZERO)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):editor.edit(body,'InformationRegister',meta,docs,r['removed_ids'])
        self.assertEqual(s.render(source),before)

    def test_root_lookup_and_absent_empty_groups(self):
        r,objects,body,_=fixture('Catalog');m=objects[s.val(objects[r['object_id']][0][3])][0]
        target=editor.edit(body,'Configuration',m,objects,[r['object_id']])
        self.assertNotIn(r['object_id'],s.render(target));self.assertIn(r['object_id'],s.render(body))

    def test_native_form_oracle_enables_only_confirmed_collection_lookup(self):
        import metadata_structure
        rows=metadata_structure.profile('ChartOfAccounts')['collections']
        form=next(row for row in rows if row['xml_name']=='Form')
        self.assertEqual(form['native']['status'],'snapshot_collection')
        self.assertIsNone(form['native']['path'])
        self.assertIn('ChartOfAccounts',metadata_structure.automatic_owners())
        unmapped=next(row for row in metadata_structure.profile('CalculationRegister')['collections'] if row['xml_name']=='Recalculation')
        self.assertEqual(unmapped['native']['status'],'unmapped')


if __name__=='__main__':unittest.main()
