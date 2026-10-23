"""Native record manager/set forms through the shared main binding builder."""
import copy,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import native_metadata as s, managed_form_xml as forms, managed_form_operations as serializer
import managed_form_profiles as profiles,managed_form_bindings as bindings
from v8unpack_backend import table_offsets
import test_catalog_form_serializer as catalog
import test_managed_form_xml as catalog_xml


class RegisterMainFormsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=json.loads(Path(__file__).with_name('fixtures').joinpath('register_main_forms_851.json').read_text(encoding='utf-8'))['cases']

    def create(self,case,xml=None):
        owner=s.Parser(case['owner']).documents()[0]
        _,_,raw=serializer.create_native(case['kind'],Path(case['form_path']).stem,'8.5.1.1529',owner,interface_xml=xml or case['xml'],module_text='// native register '+case['category'])
        return raw

    def test_all_five_native_attribute_collections_and_bindings(self):
        for case in self.cases:
            with self.subTest(kind=case['kind'],category=case['category']):
                form=forms.interface(self.create(case));expected=forms.interface(case['native'].encode('utf-8'));count=int(s.val(form[3][1]))
                self.assertEqual(s.render(form[3][:2+count]),s.render(expected[3][:2+count]))
                self.assertEqual(s.val(form[2]),'// native register '+case['category'])
                owner=s.Parser(case['owner']).documents()[0];paths=forms.object_paths(owner,case['kind'])
                key='cfg:'+case['kind']+case['category']+'.'+profiles.owner_name(owner,case['kind'])
                paths=bindings.retarget(paths,'Data',17,key in paths.main_collections)
                found={}
                def walk(value):
                    if isinstance(value,list):
                        if len(value)>12 and isinstance(value[6],s.Atom) and s.val(value[6]) in {'Data'+n for n in case['fields']}:found[s.val(value[6])]=value
                        for child in value:walk(child)
                walk(form[1]);self.assertEqual(set(found),{'Data'+n for n in case['fields']})
                for name in case['fields']:self.assertEqual(s.render(found['Data'+name][11]),s.render(paths['Data.'+name]))
                if case['category']=='RecordSet':
                    index,_,end=forms.elements.form_collection(form);table=form[1][index+2]
                    self.assertEqual(s.render(table[table_offsets(table)['path']]),'{1,{17}}')

    def test_main_name_id_order_and_paths_can_change_together(self):
        for case in self.cases:
            owner=s.Parser(case['owner']).documents()[0];root=E.fromstring(case['xml']);attrs=root.find(forms.Q+'Attributes');main=attrs[0]
            main.set('name','Запись');main.set('id','31');attrs[:]=[attrs[1],main]
            for node in root.iter(forms.Q+'DataPath'):node.text='Запись'+node.text[len('Data'):]
            raw=forms.convert(self.create(case),E.tostring(root,encoding='unicode'),paths=forms.object_paths(owner,case['kind']),object_name=profiles.owner_name(owner,case['kind']),kind=case['kind'])
            result=forms.interface(raw)
            with self.subTest(kind=case['kind'],category=case['category']):
                self.assertEqual([s.val(a[3]) for a in result[3][2:4]],['Message','Запись'])
                self.assertEqual(s.render(result[3][3][1]),'{31}')
                self.assertEqual(s.val(result[3][3][10]),'1')
                index,_,end=forms.elements.form_collection(result)
                if case['category']=='RecordSet':
                    table=result[1][index+2];self.assertEqual(s.render(table[table_offsets(table)['path']]),'{1,{31}}')
                self.assertNotIn('{17}',s.render(result[1]))

    def test_catalog_main_name_and_id_use_the_same_retargeting(self):
        root=E.fromstring(catalog_xml.xml());root.find(forms.Q+'Attributes')[0].set('name','Entity');root.find(forms.Q+'Attributes')[0].set('id','19')
        for node in root.iter(forms.Q+'DataPath'):node.text=node.text.replace('Object.','Entity.')
        raw=catalog_xml.extra(serializer.create(dict(catalog.fixture(),form_xml=E.tostring(root,encoding='unicode'))));form=forms.interface(raw)
        self.assertEqual(s.val(form[3][2][3]),'Entity');self.assertEqual(s.render(form[3][2][1]),'{19}')
        index,_,end=forms.elements.form_collection(form)
        for i in range(index+1,end,2):self.assertEqual(s.render(form[1][i+1][11][1]),'{19}')

    def test_unknown_owner_type_path_and_invalid_main_declarations_fail(self):
        for case in self.cases:
            for mutation in ('owner','type','path','number','multiple','columns'):
                root=E.fromstring(case['xml']);attrs=root.find(forms.Q+'Attributes');main=attrs[0]
                if mutation=='owner':main.find(forms.Q+'Type')[0].text+='Missing'
                elif mutation=='type':main.find(forms.Q+'Type')[0].text='xs:boolean'
                elif mutation=='path':next(root.iter(forms.Q+'DataPath')).text='Data.Missing'
                elif mutation=='number':main.set('id','2')
                elif mutation=='multiple':E.SubElement(attrs[1],forms.Q+'MainAttribute').text='true'
                else:E.SubElement(main,forms.Q+'Columns')
                with self.subTest(kind=case['kind'],mutation=mutation),self.assertRaises(ValueError):self.create(case,E.tostring(root,encoding='unicode'))

    def test_invalid_owner_generated_types_and_inline_groups_fail(self):
        for case in self.cases:
            owner=s.Parser(case['owner']).documents()[0];profile=bindings.owners()[case['kind']]
            bad=copy.deepcopy(owner);type_path=next(iter(profile['types'].values()));bad[type_path[0]][type_path[1]]=s.atom(s.ZERO)
            with self.assertRaisesRegex(ValueError,'generated type UUID'):forms.object_paths(bad,case['kind'])
            bad=copy.deepcopy(owner);bad[profile['inline_groups'][0]['slot']][1]=s.atom(999)
            with self.assertRaisesRegex(ValueError,'field collection'):forms.object_paths(bad,case['kind'])
            bad=copy.deepcopy(owner);entry=bad[profile['inline_groups'][0]['slot']][2];entry[0][1][1][1][1][2]=s.atom(s.ZERO)
            with self.assertRaisesRegex(ValueError,'field identity'):forms.object_paths(bad,case['kind'])


if __name__=='__main__':unittest.main()
