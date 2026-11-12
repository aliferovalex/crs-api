"""Ordinary owner attributes use the shared native form binding reader."""
import base64,copy,json,sys,unittest,zlib
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_graph as graph
import compiled_metadata as compiled
import native_form_bindings as bindings
import native_form_reader as forms
import native_metadata as s


class OtherInlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('native_other_inline.json').read_text(encoding='utf-8'))
        cls.cases=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))['cases']

    def body(self,case,field='body'):return s.Parser(case[field]).documents()[0]

    def test_full_native_form_accepts_ordinary_fields_alongside_the_table(self):
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                body=self.body(case)
                compiled.validate_form_interface(case['form_xml'],body,case['kind'],case['interface'].encode(),{})
                paths=forms.object_paths(body,case['kind'])
                self.assertIn('Object.Rows',paths.tables)
                for name,code in [('ExtraText','S'),('ExtraQuantity','N'),('ExtraActive','B'),('ExtraMoment','D'),('ExtraReference','#')]:
                    self.assertEqual(paths.types['Object.'+name],code)

    def test_each_native_field_binding_contains_the_declared_feature_uuid(self):
        q='{http://v8.1c.ru/8.3/MDClasses}'
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                body=self.body(case);paths=forms.object_paths(body,case['kind'])
                attrs=E.fromstring(case['xml'])[0].findall(q+'ChildObjects/'+q+'Attribute')
                self.assertEqual(len(attrs),5)
                for attr in attrs:
                    name=attr.findtext(q+'Properties/'+q+'Name');oid=attr.get('uuid')
                    self.assertEqual(s.val(paths['Object.'+name][2][1]),oid)
                    graph.common_identity(body,oid,name)

    def test_own_reference_type_is_the_owner_generated_ref_identity(self):
        q='{http://v8.1c.ru/8.3/MDClasses}';xr='{http://v8.1c.ru/8.3/xcf/readable}'
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                node=E.fromstring(case['xml'])[0]
                expected=next(n.findtext(xr+'TypeId') for n in node.findall(q+'InternalInfo/'+xr+'GeneratedType') if n.get('category')=='Ref')
                group=bindings.owners()[case['kind']]['inline_groups'][0]
                fields=self.body(case)[group['slot']][2:]
                reference=next(f for f in fields if s.val(f[0][1][1][1][2])=='ExtraReference')
                self.assertEqual(s.val(reference[0][1][1][2][1][1]),expected)

    def test_form_cannot_use_the_fields_before_they_exist(self):
        for case in self.cases:
            with self.subTest(kind=case['kind']),self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
                compiled.validate_form_paths(case['form_xml'],self.body(case,'before'),case['kind'])

    def test_duplicate_field_identity_is_rejected(self):
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                body=copy.deepcopy(self.body(case));group=bindings.owners()[case['kind']]['inline_groups'][0]
                row=body[group['slot']];row[3][0][1][1][1][1][2]=copy.deepcopy(row[2][0][1][1][1][1][2])
                with self.assertRaisesRegex(ValueError,'Duplicate or invalid register field identity'):
                    forms.object_paths(body,case['kind'])

    def test_collection_class_must_match_the_measured_owner(self):
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                body=copy.deepcopy(self.body(case));group=bindings.owners()[case['kind']]['inline_groups'][0];body[group['slot']][0]=s.atom(s.ZERO)
                with self.assertRaisesRegex(ValueError,'Invalid register field collection'):
                    forms.object_paths(body,case['kind'])


if __name__=='__main__':unittest.main()
