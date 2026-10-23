"""Complete ValueTable/ValueTree attributes compared to Configurator witnesses."""
import json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import native_metadata as s, managed_form_xml as forms, metadata_references as refs
import managed_form_elements as elements
from v8unpack_backend import table_offsets,field_offsets
import test_form_attribute_types as type_fixtures
from test_form_kinds_xml import native


class ValueCollectionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.witness=json.loads(Path(__file__).with_name('fixtures').joinpath('form_value_collections_851.json').read_text(encoding='utf-8'))
        type_fixtures.FormAttributeTypesTests.setUpClass()

    def paths(self,xml=None):
        request,_=type_fixtures.FormAttributeTypesTests().fixture()
        owner=s.Parser(type_fixtures.FormAttributeTypesTests.witness['objects'][0]['body']).documents()[0]
        paths=forms.object_paths(owner,'Catalog');paths.references=refs.resolve(xml or self.witness['xml'],request)
        return paths

    def convert(self,root=None,raw=None):
        xml=self.witness['xml'] if root is None else E.tostring(root,encoding='unicode')
        return forms.interface(forms.convert(raw or self.witness['base'].encode('utf-8'),xml,paths=self.paths(xml),object_name='CRSAPI_TestCatalog'))

    def scalar_root(self):
        root=E.fromstring(self.witness['xml']);root.remove(root.find(forms.Q+'UseForFoldersAndItems'))
        for tag,names in [('Attributes',('Rows','Nodes')),('ChildItems',('RowsTable','NodesTable'))]:
            node=root.find(forms.Q+tag);node[:]=[a for a in node if a.get('name') in names]
        for name in ('Events','Commands'):
            node=root.find(forms.Q+name)
            if node is not None:root.remove(node)
        return root

    def test_complete_attribute_rows_and_typed_bindings_match_native_oracle(self):
        form=self.convert();count=int(s.val(form[3][1]));expected=forms.interface(self.witness['native'].encode('utf-8'))
        self.assertEqual(s.render(form[3][:2+count]),s.render(expected[3][:2+count]))
        paths=forms.attributes_from_xml(forms.interface(self.witness['base'].encode('utf-8')),self.scalar_root().find(forms.Q+'Attributes'),self.paths())
        self.assertTrue({'Rows','Nodes'}<=paths.tables)
        for table,number in [('Rows',200),('Nodes',201)]:
            self.assertEqual(s.render(paths[table]),'{1,{'+str(number)+'}}')
            for column in ('Label','Amount','Active','Reference','Mixed','Moment'):
                self.assertEqual(s.render(paths[table+'.'+column]),self.witness['paths'][table+column])
            self.assertEqual(paths.types[table+'.Active'],'B');self.assertIsNone(paths.types[table+'.Mixed'])
        index,_,end=elements.form_collection(form)
        name_slot=elements.layouts()['elements']['Table']['name_slot']
        tables={s.val(form[1][i+1][name_slot]):form[1][i+1] for i in range(index+1,end,2) if s.val(form[1][i+1][name_slot]) in ('RowsTable','NodesTable')}
        self.assertEqual(set(tables),{'RowsTable','NodesTable'})
        for name,entry in tables.items():
            offset=table_offsets(entry);start=offset['children'];count,_,stop=elements.collection(entry,start)
            self.assertEqual(s.render(entry[offset['path']]),s.render(paths[name.removesuffix('Table')]))
            for addition in entry:
                if isinstance(addition,list) and addition and isinstance(addition[0],s.Atom) and s.val(addition[0])=='6':
                    self.assertEqual(s.val(addition[19][0]),s.val(entry[1][0]))
            for i in range(start+1,stop,2):
                field=entry[i+1];self.assertEqual(s.render(field[field_offsets(field)['path']]),self.witness['paths'][s.val(field[6])])

    def test_new_common_form_and_existing_owner_form_share_collection_builder(self):
        root=self.scalar_root();xml=E.tostring(root,encoding='unicode');paths=self.paths(xml)
        form=forms.interface(forms.convert(native('CommonForm'),xml,paths=paths,kind='CommonForm'))
        self.assertEqual(s.val(form[3][1]),'2')
        self.assertEqual([s.render(a) for a in form[3][2:4]],[self.witness['attributes'][n] for n in ('Rows','Nodes')])
        # Only the column Ref requires the catalog; the attribute itself is intrinsic.
        request,_=type_fixtures.FormAttributeTypesTests().fixture();plan=refs.plan(dict(request,xml=xml))
        self.assertEqual(plan['objects'],[dict(object_id=type_fixtures.FormAttributeTypesTests.witness['objects'][0]['object_id'],name='CRSAPI_TestCatalog')])

    def test_column_order_rename_type_change_and_removal_follow_complete_xml(self):
        root=self.scalar_root();rows=root.find(forms.Q+'Attributes')[0];columns=rows.find(forms.Q+'Columns')
        columns[:]=[columns[2],columns[0]];columns[1].set('name','Caption')
        fields=root.find(forms.Q+'ChildItems')[0].find(forms.Q+'ChildItems');fields[:]=[fields[2],fields[0]]
        fields[1].find(forms.Q+'DataPath').text='Rows.Caption'
        new_type=E.fromstring('<Type xmlns="'+forms.NS+'" xmlns:v8="'+forms.CORE+'"><v8:Type>xs:boolean</v8:Type></Type>')
        columns[1].remove(columns[1].find(forms.Q+'Type'));columns[1].append(new_type)
        form=self.convert(root);entry=form[3][2]
        self.assertEqual(s.val(entry[13]),'2');self.assertEqual([s.val(c[3]) for c in entry[14:16]],['Active','Caption'])
        self.assertEqual(s.render(entry[15][5]),'{"Pattern",{"B"}}')
        columns[:]=[];fields[:]=[]
        empty=self.convert(root,s.native_body_bytes([form]));self.assertEqual(s.val(empty[3][2][13]),'0')
        self.assertEqual(len(empty[3][2]),16)

    def test_deleted_or_foreign_column_bindings_and_scalar_table_binding_fail(self):
        for case in ('deleted','foreign','collection_input','scalar_table','checkbox'):
            root=self.scalar_root();attrs=root.find(forms.Q+'Attributes');items=root.find(forms.Q+'ChildItems');table=items[0];field=table.find(forms.Q+'ChildItems')[0]
            if case=='deleted':attrs[0].find(forms.Q+'Columns').remove(attrs[0].find(forms.Q+'Columns')[0])
            elif case=='foreign':field.find(forms.Q+'DataPath').text='Nodes.Label'
            elif case=='collection_input':field.find(forms.Q+'DataPath').text='Rows'
            elif case=='scalar_table':table.find(forms.Q+'DataPath').text='Rows.Label'
            else:field.tag=forms.Q+'CheckBoxField'
            with self.subTest(case=case),self.assertRaises(ValueError):self.convert(root)

    def test_invalid_columns_nested_collections_and_unknown_properties_fail(self):
        for case in ('id','name','unknown','scalar','nested','qualifier'):
            root=self.scalar_root();attr=root.find(forms.Q+'Attributes')[0];cols=attr.find(forms.Q+'Columns')
            if case=='id':cols[1].set('id','1')
            elif case=='name':cols[1].set('name','label')
            elif case=='unknown':E.SubElement(cols[0],forms.Q+'Settings')
            elif case=='scalar':attr.find(forms.Q+'Type')[0].text='xs:boolean'
            elif case=='nested':cols[0].find(forms.Q+'Type')[0].text='v8:ValueTable'
            else:E.SubElement(attr.find(forms.Q+'Type'),'{'+forms.CORE+'}StringQualifiers')
            with self.subTest(case=case),self.assertRaises(ValueError):self.convert(root)

    def test_titles_replace_and_clear_for_attributes_and_columns(self):
        root=self.scalar_root();rows=root.find(forms.Q+'Attributes')[0]
        rows.find(forms.Q+'Title')[0][1].text='New title';column=rows.find(forms.Q+'Columns')[0];column.remove(column.find(forms.Q+'Title'))
        form=self.convert(root)
        self.assertEqual(s.val(form[3][2][4][2][1]),'New title')
        self.assertEqual(s.render(form[3][2][14][4]),'{1,0}')

    def test_explicit_native_auxiliary_identity_is_preserved_and_can_be_renamed(self):
        root=E.fromstring(self.witness['xml']);code=next(n for n in root.iter(forms.Q+'InputField') if n.get('name')=='Code')
        xml=code.find(forms.Q+'ContextMenu');xml.set('name','CodeCustomMenu');xml.set('id','9999')
        form=self.convert(root)
        def controls(value):
            if isinstance(value,list):
                if len(value)>6 and isinstance(value[6],s.Atom) and s.val(value[6])=='CodeCustomMenu':yield value
                for child in value:yield from controls(child)
        menu=next(controls(form[1]));self.assertEqual(s.val(menu[1][0]),'9999')
        self.assertEqual(len(menu[1]),2)

    def test_invalid_native_addition_binding_is_rejected(self):
        form=self.convert();index,_,end=elements.form_collection(form)
        name_slot=elements.layouts()['elements']['Table']['name_slot']
        table=next(form[1][i+1] for i in range(index+1,end,2) if s.val(form[1][i+1][name_slot])=='RowsTable')
        addition=next(v for v in table if isinstance(v,list) and v and isinstance(v[0],s.Atom) and s.val(v[0])=='6')
        addition[19][1]=s.atom(99)
        with self.assertRaisesRegex(ValueError,'table addition binding'):self.convert(raw=s.native_body_bytes([form]))


if __name__=='__main__':unittest.main()
