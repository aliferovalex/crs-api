"""Standard row numbers from independent native forms of all tabular owners."""
import base64,copy,json,sys,unittest,zlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_metadata as compiled
import native_form_reader as forms
import native_metadata as s
import native_tabular as tabular


def lists(value):
    if isinstance(value,list):
        yield value
        for child in value:yield from lists(child)


class TabularStandardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('native_tabular_standard.json').read_text(encoding='utf-8'))
        cls.cases=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))['cases']

    def body(self,case,key='body'):return s.Parser(case[key]).documents()[0]

    def test_native_examples_cover_every_supported_tabular_owner(self):
        for phase in ('default','minimum','rename'):
            self.assertEqual({c['kind'] for c in self.cases if c['phase']==phase},set(tabular.kinds()))

    def test_complete_native_forms_validate_in_all_modes(self):
        for case in self.cases:
            with self.subTest(kind=case['kind'],phase=case['phase']):
                compiled.validate_form_interface(case['form_xml'],self.body(case),case['kind'],case['interface'].encode(),{})

    def test_number_binding_matches_measured_native_control_and_section_uuid(self):
        for case in self.cases:
            with self.subTest(kind=case['kind'],phase=case['phase']):
                body=self.body(case);section,=tabular.collection(body,case['kind']);common=tabular.common(section)
                path='Object.'+s.val(common[2])+'.LineNumber';paths=forms.object_paths(body,case['kind'])
                expected='{3,{1},{0,'+s.val(common[1][2])+'},{-2}}'
                self.assertEqual(s.render(paths[path]),expected);self.assertEqual(paths.types[path],'N');self.assertNotIn(path,paths.tables)
                controls=[row for row in lists(s.Parser(case['interface']).documents())
                          if any(isinstance(v,s.Atom) and v.quoted and s.val(v)=='RowsLineNumber' for v in row)]
                self.assertEqual(len(controls),1)
                self.assertEqual(sum(s.render(row)==expected for row in lists(controls[0])),1)

    def test_rename_and_number_length_keep_native_identity_binding(self):
        for kind in tabular.kinds():
            rows={c['phase']:c for c in self.cases if c['kind']==kind};first=forms.object_paths(self.body(rows['default']),kind)
            for phase,name in [('minimum','Rows'),('rename','RenamedRows')]:
                paths=forms.object_paths(self.body(rows[phase]),kind)
                self.assertEqual(s.render(first['Object.Rows.LineNumber']),s.render(paths['Object.'+name+'.LineNumber']))
                if phase=='rename':self.assertNotIn('Object.Rows.LineNumber',paths)
            with self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
                compiled.validate_form_paths(rows['default']['form_xml'],self.body(rows['rename']),kind)

    def test_missing_section_does_not_provide_a_standard_column(self):
        for case in self.cases:
            if case['phase']!='default':continue
            with self.subTest(kind=case['kind']):
                before=self.body(case,'before');paths=forms.object_paths(before,case['kind'])
                self.assertNotIn('Object.Rows.LineNumber',paths)
                with self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
                    compiled.validate_form_paths(case['form_xml'],before,case['kind'])

    def test_user_column_cannot_shadow_standard_number_even_with_different_case(self):
        for case in self.cases:
            if case['phase']!='default':continue
            for name in ('LineNumber','linenumber'):
                with self.subTest(kind=case['kind'],name=name):
                    body=copy.deepcopy(self.body(case));section,=tabular.collection(body,case['kind'])
                    tabular.attributes(section)[0][0][1][1][1][2]=s.atom(name,True)
                    with self.assertRaisesRegex(ValueError,'Ambiguous tabular attribute'):
                        forms.object_paths(body,case['kind'])

    def test_standard_number_belongs_to_the_section_not_the_owner(self):
        for case in self.cases:
            if case['phase']!='default':continue
            with self.subTest(kind=case['kind']):
                body=self.body(case);self.assertNotIn('Object.LineNumber',forms.object_paths(body,case['kind']))
                xml=case['form_xml'].replace('Object.Rows.LineNumber','Object.LineNumber')
                with self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
                    compiled.validate_form_paths(xml,body,case['kind'])


if __name__=='__main__':unittest.main()
