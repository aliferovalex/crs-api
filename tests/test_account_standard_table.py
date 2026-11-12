"""Measured standard subkonto table paths and availability in account charts."""
import base64,copy,json,sys,unittest,zlib
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_dependencies as deps
import compiled_graph as graph
import compiled_metadata as compiled
import native_form_bindings as bindings
import native_form_reader as forms
import native_metadata as s


def lists(value):
    if isinstance(value,list):
        yield value
        for child in value:yield from lists(child)


class AccountStandardTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('native_account_standard_table.json').read_text())
        cls.cases={row['phase']:row for row in json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))['cases']}

    def body(self,case):return s.Parser(case['body']).documents()[0]

    def test_complete_native_forms_match_every_owner_mode(self):
        for phase,case in self.cases.items():
            with self.subTest(phase=phase):
                compiled.validate_form_interface(case['form_xml'],self.body(case),'ChartOfAccounts',case['interface'].encode(),{})
                bindings.validate_owner_properties(E.fromstring(case['xml'])[0],self.body(case),'ChartOfAccounts')

    def test_exact_table_and_column_markers_equal_native_controls(self):
        for phase in ('enabled','three-linked'):
            case=self.cases[phase];paths=forms.object_paths(self.body(case),'ChartOfAccounts');native=list(lists(s.Parser(case['interface']).documents()))
            self.assertIn('Object.ExtDimensionTypes',paths.tables)
            self.assertEqual(s.render(paths['Object.ExtDimensionTypes']),'{2,{1},{-12}}')
            for name,marker,typ in [('LineNumber',-12,'N'),('ExtDimensionType',-13,'#'),('TurnoversOnly',-15,'B')]:
                path='Object.ExtDimensionTypes.'+name;expected='{3,{1},{-12},{'+str(marker)+'}}'
                self.assertEqual(s.render(paths[path]),expected);self.assertEqual(paths.types[path],typ)
                control=next(row for row in native if any(isinstance(v,s.Atom) and v.quoted and s.val(v)=='Dimension'+name for v in row))
                self.assertEqual(sum(s.render(row)==expected for row in lists(control)),1)

    def test_zero_count_disables_table_and_all_columns_even_with_a_plan(self):
        for phase in ('disabled-linked','disabled-empty'):
            case=self.cases[phase];body=self.body(case);paths=forms.object_paths(body,'ChartOfAccounts')
            self.assertFalse(any(key.startswith('Object.ExtDimensionTypes') for key in paths))
            with self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
                compiled.validate_form_paths(self.cases['enabled']['form_xml'],body,'ChartOfAccounts')

    def test_missing_characteristic_plan_cannot_enable_columns(self):
        body=copy.deepcopy(self.body(self.cases['enabled']));body[1][19]=s.atom(s.ZERO)
        self.assertNotIn('Object.ExtDimensionTypes',forms.object_paths(body,'ChartOfAccounts'))

    def test_native_maximum_count_must_match_xml_before_packet_assembly(self):
        case=self.cases['enabled'];node=E.fromstring(case['xml'])[0];node.find('{http://v8.1c.ru/8.3/MDClasses}Properties/{http://v8.1c.ru/8.3/MDClasses}MaxExtDimensionCount').text='3'
        with self.assertRaisesRegex(ValueError,'Native owner property differs from XML: ChartOfAccounts.MaxExtDimensionCount'):
            bindings.validate_owner_properties(node,self.body(case),'ChartOfAccounts')

    def test_selected_characteristic_plan_resolves_to_repository_dependency(self):
        for phase in ('enabled','three-linked'):
            case=self.cases[phase];records={r['id']:dict(r,node=E.fromstring(r['xml'])[0]) for r in case['records']};image={k:v.encode('utf-8-sig') for k,v in case['image'].items()};index=graph.TypeIndex(records,image);oid=E.fromstring(case['xml'])[0].get('uuid')
            for key in records:index.facts(key)
            references=deps.references(index,records[oid],image[oid],image,case['xml']);target=next(key for key,row in records.items() if row['kind']=='ChartOfCharacteristicTypes')
            self.assertEqual(references[target],0)


if __name__=='__main__':unittest.main()
