import copy,json,unittest,sys,uuid
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/Сериализация'))
import native_metadata as s, managed_form_xml as x, managed_form_operations as creation
import tabular_section_xml as tabular,v8unpack_backend as backend
import test_tabular_section_xml as fixtures
import test_managed_form_xml as forms


def owner(kind='Catalog'):
    _,body=fixtures.source()
    if kind=='Document':
        profile=json.loads(Path(x.__file__).with_name('document_layout_851.json').read_text(encoding='utf-8'))
        body=s.Parser(profile['template']).documents()[0]
        for field in profile['generated_slots']:body[1][field]=s.atom(str(uuid.uuid5(uuid.NAMESPACE_URL,'document/type/'+str(field))))
        import managed_form_profiles
        common=managed_form_profiles.owner_common(body,kind);common[1][2]=s.atom(str(uuid.uuid5(uuid.NAMESPACE_URL,'document/owner')));common[2]=s.atom('XML_Catalog',True)
    node=fixtures.section()
    if kind=='Document':
        for typ in node.find(tabular.Q+'InternalInfo'):
            typ.set('name',typ.get('name').replace('Catalog','Document',1))
    _,_,section,_,_=tabular.read(node,'XML_Catalog',kind=kind)
    slot=5 if kind=='Catalog' else 3
    body[slot].append(section);body[slot][1]=s.atom(1)
    return body


def xml(columns=('Text','Quantity')):
    root=E.fromstring(forms.xml());items=root.find(x.Q+'ChildItems');items.clear()
    table=E.SubElement(items,x.Q+'Table',name='RowsTable',id='50')
    E.SubElement(table,x.Q+'DataPath').text='Object.Rows'
    fields=E.SubElement(table,x.Q+'ChildItems')
    for i,name in enumerate(columns):
        field=E.SubElement(fields,x.Q+'InputField',name='Rows'+name,id=str(60+i*10))
        E.SubElement(field,x.Q+'DataPath').text='Object.Rows.'+name
    return root


def convert(root,native=None):
    body=owner();paths=x.object_paths(body,'Catalog')
    text=E.tostring(root,encoding='unicode')
    if native is None:return creation.create_native('Catalog','TableForm','8.5.1.1529',body,interface_xml=text)[2]
    return x.convert(native,text,paths=paths,object_name='XML_Catalog')


class TableTests(unittest.TestCase):
    def test_binding_ids_come_from_owner_for_catalog_and_document(self):
        for kind in ['Catalog','Document']:
            paths=x.object_paths(owner(kind),kind)
            self.assertIn('Object.Rows',paths.tables)
            self.assertEqual(s.render(paths['Object.Rows.Text']),'{3,{1},{0,'+fixtures.SID+'},{0,'+fixtures.AID+'}}')

    def test_upstream_tree_contains_table_and_columns(self):
        raw=convert(xml());model=backend.form_model(x.interface(raw));tree=model['elements']['tree']
        self.assertEqual(tree[0]['type'],'Table')
        self.assertEqual([n['name'] for n in tree[0]['child']],['RowsText','RowsQuantity'])

    def test_full_file_reorders_removes_columns_and_preserves_tail_flags(self):
        raw=convert(xml());root=xml();table=root.find(x.Q+'ChildItems')[0];cols=table.find(x.Q+'ChildItems');cols.remove(cols[0])
        E.SubElement(table,x.Q+'Visible').text='false';E.SubElement(table,x.Q+'ReadOnly').text='true'
        changed=convert(root,raw);form=x.interface(changed);i,_,_=x.elements.form_collection(form);entry=form[1][i+2]
        index=backend.table_offsets(entry)['children'];self.assertEqual(s.val(entry[index]),'1')
        self.assertEqual(s.val(entry[index+2][6]),'RowsQuantity');self.assertEqual(s.val(entry[index+5]),'0');self.assertEqual(s.val(entry[14]),'1')
        cols.clear();empty=convert(root,changed);model=backend.form_model(x.interface(empty))
        self.assertFalse(model['elements']['tree'][0].get('child'))
        table_root=root.find(x.Q+'ChildItems');table_root.clear()
        no_table=convert(root,empty);self.assertFalse(backend.form_model(x.interface(no_table))['elements']['tree'])

    def test_rejects_collection_as_field_foreign_column_and_nonempty_filter(self):
        root=xml();table=root.find(x.Q+'ChildItems')[0]
        bad=copy.deepcopy(root);bad.find('.//'+x.Q+'InputField/'+x.Q+'DataPath').text='Object.Rows'
        other=copy.deepcopy(root);other.find('.//'+x.Q+'InputField/'+x.Q+'DataPath').text='Object.Code'
        filtered=copy.deepcopy(root);E.SubElement(filtered.find('.//'+x.Q+'Table'),x.Q+'RowFilter').text='selection'
        for value in [bad,other,filtered]:
            with self.assertRaises(ValueError):convert(value)

    def test_table_requires_a_collection_binding(self):
        root=xml();root.find('.//'+x.Q+'Table/'+x.Q+'DataPath').text='Object.Code'
        with self.assertRaisesRegex(ValueError,'Table DataPath'):convert(root)


if __name__=='__main__':unittest.main()
