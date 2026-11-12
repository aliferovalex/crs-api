"""Native standard fields of account charts and characteristic plans."""
import base64,copy,json,sys,unittest,zlib
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_metadata as compiled
import native_form_bindings as bindings
import native_form_reader as forms
import native_metadata as s

Q='{http://v8.1c.ru/8.3/MDClasses}';F='{http://v8.1c.ru/8.3/xcf/logform}'
FIELDS={'ChartOfAccounts':{'Ref':-2,'DeletionMark':-4,'Parent':-6,'Type':-10,'OffBalance':-11,'Predefined':-5,'PredefinedDataName':-28,'Code':-7,'Description':-8,'Order':-17},'ChartOfCharacteristicType':{'Ref':-2,'DeletionMark':-4,'Parent':-6,'IsFolder':-7,'Predefined':-5,'PredefinedDataName':-14,'Code':-8,'Description':-9,'ValueType':-11}}


def lists(value):
    if isinstance(value,list):
        yield value
        for child in value:yield from lists(child)


class ChartStandardFieldsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('native_chart_standard_fields.json').read_text())
        cls.cases=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))['cases']

    def case(self,phase,kind):return next(c for c in self.cases if c['phase']==phase and c['kind']==kind)
    def body(self,case):return s.Parser(case['body']).documents()[0]

    def test_native_cases_cover_both_owners_and_five_modes(self):
        self.assertEqual({(c['kind'],c['phase']) for c in self.cases},{(kind,phase) for kind in FIELDS for phase in ('enabled','flat','no-codes','no-descriptions','no-order')})

    def test_complete_native_forms_and_owner_properties_validate(self):
        for case in self.cases:
            with self.subTest(kind=case['kind'],phase=case['phase']):
                body=self.body(case);bindings.validate_owner_properties(E.fromstring(case['xml'])[0],body,case['kind'])
                compiled.validate_form_interface(case['form_xml'],body,case['kind'],case['interface'].encode(),{})

    def test_every_measured_standard_marker_matches_its_native_control(self):
        for case in self.cases:
            native=list(lists(s.Parser(case['interface']).documents()));paths=forms.object_paths(self.body(case),case['kind'])
            for node in E.fromstring(case['form_xml']).iter():
                name=node.get('name','')
                if not name.startswith('Std') or name[3:] not in FIELDS[case['kind']]:continue
                path=node.findtext(F+'DataPath');expected='{2,{1},{'+str(FIELDS[case['kind']][name[3:]])+'}}'
                self.assertEqual(s.render(paths[path]),expected)
                control=next(row for row in native if any(isinstance(v,s.Atom) and v.quoted and s.val(v)==name for v in row))
                self.assertEqual(sum(s.render(row)==expected for row in lists(control)),1)

    def test_availability_follows_lengths_and_characteristic_hierarchy(self):
        for case in self.cases:
            expected=set(FIELDS[case['kind']]);props=E.fromstring(case['xml'])[0].find(Q+'Properties');paths=forms.object_paths(self.body(case),case['kind'])
            for prop in ('Code','Description','Order'):
                if props.findtext(Q+prop+'Length')=='0':expected.discard(prop)
            if case['kind']=='ChartOfCharacteristicType' and props.findtext(Q+'Hierarchical')=='false':expected-={'Parent','IsFolder'}
            self.assertEqual({name for name in FIELDS[case['kind']] if 'Object.'+name in paths},expected)

    def test_stale_paths_are_rejected_after_disabling_fields(self):
        for kind in FIELDS:
            before=self.case('enabled',kind)
            for phase in ('no-codes','no-descriptions',*(['flat'] if kind=='ChartOfCharacteristicType' else ['no-order'])):
                with self.subTest(kind=kind,phase=phase),self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
                    compiled.validate_form_paths(before['form_xml'],self.body(self.case(phase,kind)),kind)

    def test_native_mode_fidelity_guards_reject_disagreement_with_xml(self):
        for kind in FIELDS:
            case=self.case('enabled',kind)
            for name,rule in bindings.owners()[kind]['native_property_checks'].items():
                if name=='MaxExtDimensionCount':continue
                body=copy.deepcopy(self.body(case));path=rule['path'];parent=bindings.at(body,path[:-1]);value=s.val(parent[path[-1]])
                parent[path[-1]]=s.atom(int(value)+1 if rule.get('integer') else '0' if value=='1' else '1')
                with self.subTest(kind=kind,property=name),self.assertRaisesRegex(ValueError,'Native owner property differs from XML'):
                    bindings.validate_owner_properties(E.fromstring(case['xml'])[0],body,kind)

    def test_data_version_is_not_a_form_path_and_builtin_types_are_not_guessed(self):
        for kind in FIELDS:
            paths=forms.object_paths(self.body(self.case('enabled',kind)),kind)
            self.assertNotIn('Object.DataVersion',paths)
            self.assertIsNone(paths.types['Object.'+('Type' if kind=='ChartOfAccounts' else 'ValueType')])


if __name__=='__main__':unittest.main()
