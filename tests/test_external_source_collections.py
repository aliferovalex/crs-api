"""Native collection removal retains opaque external-source properties."""
import copy,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import metadata_structure as structure,metadata_owner_profiles as owners
import metadata_owner_change as change,native_collection_editor as editor
import native_metadata as s,metadata_identifiers as ids,metadata_context
import preparation_plan
from test_catalog_form_serializer import fixture


class ExternalSourceCollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case=json.loads(Path(__file__).with_name('fixtures').joinpath('external_source_collections_851.json').read_text(encoding='utf-8'))

    def descriptors(self):
        request=fixture();template=metadata_context.context_objects(request['context'])[request['object_id']]
        source=s.Parser(self.case['source']).documents()[0];objects={};rows=[]
        xml=E.fromstring(self.case['before_xml']);q=change.xml_namespaces.MD;q='{'+q+'}'
        for kind,slot in self.case['collections'].items():
            row=source[slot[0]];rows.append([row[0],s.atom(len(row)-2)]+copy.deepcopy(row[2:]))
            names=[node.text for node in xml[0].find(q+'ChildObjects') if node.tag==q+kind]
            for index,(atom,name) in enumerate(zip(row[2:],names)):
                oid=s.val(atom);docs=copy.deepcopy(template);m=docs[0]
                m[1],m[2],m[3],m[4],m[9],m[10]=s.atom(oid),s.atom(ids.class_id(kind)),s.atom(self.case['id']),s.atom(s.ZERO),s.atom(name,True),s.atom(index)
                for field in (11,12,13,14):m[field]=[s.atom(0)]
                docs[2]=[s.atom(0)];objects[oid]=docs
        docs=copy.deepcopy(template);m=docs[0];m[1]=s.atom(self.case['id']);m[2]=s.atom(ids.class_id('ExternalDataSource'))
        m[9]=copy.deepcopy(owners.owner_common(source,'ExternalDataSource')[2]);m[12]=[s.atom(len(rows))]+rows
        objects[self.case['id']]=docs
        return source,m,objects

    def test_existing_container_is_supported_without_claiming_creation_or_forms(self):
        self.assertIn('ExternalDataSource',preparation_plan.CHANGE);self.assertNotIn('ExternalDataSource',preparation_plan.CREATE)
        self.assertIn('ExternalDataSource',structure.automatic_owners())
        self.assertEqual(structure.profile('ExternalDataSource')['native_identity_path'],self.case['identity_path'])
        import managed_form_profiles
        self.assertNotIn('ExternalDataSource',managed_form_profiles.owner_profiles())

    def test_native_table_and_cube_removal_matches_independent_designer_body(self):
        source,m,objects=self.descriptors();removed=set(objects)-{self.case['id']}
        raw=self.case['source'].encode('utf-8');actual=editor.edit_raw(raw,'ExternalDataSource',m,objects,removed)
        expected=s.Parser(self.case['body']).documents()
        self.assertEqual(s.render(s.Parser(actual.decode('utf-8-sig')).documents()),s.render(expected))
        for row in editor.inspect(source,'ExternalDataSource',m,objects):
            single=editor.edit(source,'ExternalDataSource',m,objects,row['ids'])
            other=next(r for r in editor.inspect(source,'ExternalDataSource',m,objects) if r['path']!=row['path'])
            self.assertEqual(s.render(editor.at(single,other['path'])),s.render(editor.at(source,other['path'])))

    def test_native_identity_class_and_context_rows_remain_checked(self):
        source,m,objects=self.descriptors();bad=copy.deepcopy(source)
        editor.at(bad,[1,1,1,1])[2]=s.atom('aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee')
        with self.assertRaisesRegex(ValueError,'UUID differs'):editor.inspect(bad,'ExternalDataSource',m,objects)
        bad=copy.deepcopy(source);bad[3][0]=s.atom(ids.class_id('Table'))
        with self.assertRaisesRegex(ValueError,'Invalid native stored collection'):editor.inspect(bad,'ExternalDataSource',m,objects)
        oid=next(oid for oid in objects if oid!=self.case['id']);objects[oid][0][3]=s.atom(s.ZERO)
        with self.assertRaisesRegex(ValueError,'parent or position'):editor.inspect(source,'ExternalDataSource',m,objects)

    def test_stored_names_are_separate_but_opaque_inline_functions_remain_compared(self):
        before=E.fromstring(self.case['before_xml']);after=E.fromstring(self.case['xml'])
        self.assertEqual(change.retained_xml(before,'ExternalDataSource'),change.retained_xml(after,'ExternalDataSource'))
        q='{'+change.xml_namespaces.MD+'}';E.SubElement(after[0].find(q+'ChildObjects'),q+'Function',uuid='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee')
        self.assertNotEqual(change.retained_xml(before,'ExternalDataSource'),change.retained_xml(after,'ExternalDataSource'))


if __name__=='__main__':unittest.main()
