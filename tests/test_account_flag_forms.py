"""Native accounting flags use separate object and subkonto column scopes."""
import base64,copy,json,sys,unittest,zlib
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_graph as graph
import compiled_metadata as compiled
import native_form_reader as forms
import native_metadata as s


def lists(value):
    if isinstance(value,list):
        yield value
        for child in value:yield from lists(child)


class AccountFlagFormsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('native_account_flag_forms.json').read_text())
        cls.cases={r['phase']:r for r in json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))['cases']}

    def body(self,phase):return s.Parser(self.cases[phase]['body']).documents()[0]

    def test_complete_native_forms_validate_for_every_operation(self):
        for phase,case in self.cases.items():
            with self.subTest(phase=phase):
                compiled.validate_form_interface(case['form_xml'],self.body(phase),'ChartOfAccounts',case['interface'].encode(),{})

    def test_both_scopes_bind_native_flag_uuids_and_all_five_types(self):
        body=self.body('enabled');paths=forms.object_paths(body,'ChartOfAccounts');native=list(lists(s.Parser(self.cases['enabled']['interface']).documents()))
        for slot,prefix,controlprefix in [(8,'Object.','Account'),(9,'Object.ExtDimensionTypes.','Dimension')]:
            for flag in body[slot][2:]:
                common=flag[0][1][1][1];name=s.val(common[2]);oid=s.val(common[1][2]);key=prefix+name
                expected=('{2,{1},{0,'+oid+'}}' if slot==8 else '{3,{1},{-12},{0,'+oid+'}}')
                self.assertEqual(s.render(paths[key]),expected)
                control=next(row for row in native if any(isinstance(v,s.Atom) and v.quoted and s.val(v)==controlprefix+name for v in row))
                self.assertEqual(sum(s.render(row)==expected for row in lists(control)),1)
                self.assertEqual(paths.types[key],dict(FlagBool='B',FlagNumber='N',FlagString='S',FlagDate='D',FlagRef='#')[name])

    def test_identical_names_in_distinct_scopes_are_not_ambiguous(self):
        paths=forms.object_paths(self.body('enabled'),'ChartOfAccounts')
        for suffix in ('Bool','Number','String','Date','Ref'):
            self.assertNotEqual(s.render(paths['Object.Flag'+suffix]),s.render(paths['Object.ExtDimensionTypes.Flag'+suffix]))

    def test_rename_preserves_uuid_bindings_in_both_scopes(self):
        before=forms.object_paths(self.body('enabled'),'ChartOfAccounts');after=forms.object_paths(self.body('rename'),'ChartOfAccounts')
        for prefix in ('Object.','Object.ExtDimensionTypes.'):
            self.assertNotIn(prefix+'FlagBool',after)
            self.assertEqual(s.render(before[prefix+'FlagBool']),s.render(after[prefix+'RenamedFlagBool']))
        with self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
            compiled.validate_form_paths(self.cases['enabled']['form_xml'],self.body('rename'),'ChartOfAccounts')

    def test_removal_drops_both_flag_paths_and_rejects_stale_form(self):
        paths=forms.object_paths(self.body('remove'),'ChartOfAccounts')
        self.assertNotIn('Object.FlagRef',paths);self.assertNotIn('Object.ExtDimensionTypes.FlagRef',paths)
        with self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
            compiled.validate_form_paths(self.cases['enabled']['form_xml'],self.body('remove'),'ChartOfAccounts')

    def test_disabling_subkonto_hides_nested_flags_but_keeps_object_flags(self):
        body=self.body('disabled');paths=forms.object_paths(body,'ChartOfAccounts')
        self.assertEqual(len(body[9])-2,5)
        self.assertFalse(any(key.startswith('Object.ExtDimensionTypes') for key in paths))
        for suffix in ('Bool','Number','String','Date','Ref'):self.assertIn('Object.Flag'+suffix,paths)

    def test_flag_uuid_cannot_be_reused_across_scopes_even_when_disabled(self):
        for phase in ('enabled','disabled'):
            body=copy.deepcopy(self.body(phase));body[9][2][0][1][1][1][1][2]=body[8][2][0][1][1][1][1][2]
            with self.assertRaisesRegex(ValueError,'Duplicate or invalid register field identity'):
                forms.object_paths(body,'ChartOfAccounts')

    def test_flags_cannot_shadow_standard_fields_or_columns(self):
        for slot,name,error in [(8,'Code','shadows a standard field'),(9,'LineNumber','shadows a standard column'),(9,'turnoversonly','shadows a standard column')]:
            body=copy.deepcopy(self.body('enabled'));body[slot][2][0][1][1][1][2]=s.atom(name,True)
            with self.assertRaisesRegex(ValueError,error):forms.object_paths(body,'ChartOfAccounts')

    def test_wrong_flag_collection_class_or_count_is_rejected(self):
        for phase in ('enabled','disabled'):
            for slot in (8,9):
                for index,value in [(0,s.atom(s.ZERO)),(1,s.atom(0))]:
                    body=copy.deepcopy(self.body(phase));body[slot][index]=value
                    with self.assertRaisesRegex(ValueError,'Invalid register field collection'):
                        forms.object_paths(body,'ChartOfAccounts')

    def test_common_identity_index_proves_all_declared_flag_features(self):
        q='{http://v8.1c.ru/8.3/MDClasses}'
        for phase,case in self.cases.items():
            records={r['id']:dict(r,node=E.fromstring(r['xml'])[0]) for r in case['records']};image={k:v.encode('utf-8-sig') for k,v in case['image'].items()};index=graph.TypeIndex(records,image);node=E.fromstring(case['xml'])[0];oid=node.get('uuid')
            expected={n.get('uuid') for n in node.iter() if n.tag in (q+'AccountingFlag',q+'ExtDimensionAccountingFlag')}
            self.assertEqual(set(index.facts(oid).features),expected)


if __name__=='__main__':unittest.main()
