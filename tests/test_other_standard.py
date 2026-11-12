"""Standard object paths agree with independent Configurator bindings and modes."""
import base64,copy,json,sys,unittest,zlib
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_metadata as compiled
import compiled_graph as graph
import native_form_bindings as bindings
import native_form_reader as forms
import native_metadata as s

Q='{http://v8.1c.ru/8.3/MDClasses}'
F='{http://v8.1c.ru/8.3/xcf/logform}'


def lists(value):
    if isinstance(value,list):
        yield value
        for child in value:yield from lists(child)


class OtherStandardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('native_other_standard.json').read_text(encoding='utf-8'))
        data=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))
        cls.cases=data['cases'];cls.mismatch=data['ibcmd_mismatch']

    def body(self,case):return s.Parser(case['body']).documents()[0]
    def case(self,phase,kind):return next(c for c in self.cases if (c['phase'],c['kind'])==(phase,kind))

    def test_native_whole_forms_match_final_owners_in_all_fifteen_cases(self):
        for case in self.cases:
            with self.subTest(phase=case['phase'],kind=case['kind']):
                compiled.validate_form_interface(case['form_xml'],self.body(case),case['kind'],case['interface'].encode(),{})

    def test_every_standard_path_matches_its_measured_native_binding(self):
        measured=set()
        for case in self.cases:
            with self.subTest(phase=case['phase'],kind=case['kind']):
                paths=forms.object_paths(self.body(case),case['kind']);native=list(lists(s.Parser(case['interface']).documents()))
                controls=[n for n in E.fromstring(case['form_xml']).iter() if n.get('name','').startswith('Std') and n.find(F+'DataPath') is not None]
                for control in controls:
                    name=control.get('name');path=control.findtext(F+'DataPath')
                    rows=[row for row in native if any(isinstance(v,s.Atom) and v.quoted and s.val(v)==name for v in row)]
                    self.assertEqual(len(rows),1,name)
                    found=[row for row in lists(rows[0]) if len(row)==3 and isinstance(row[0],s.Atom) and s.val(row[0])=='2'
                           and s.render(row[1])=='{1}' and isinstance(row[2],list) and len(row[2])==1 and isinstance(row[2][0],s.Atom) and s.val(row[2][0]).startswith('-')]
                    self.assertEqual(len(found),1,path)
                    self.assertEqual(s.render(paths[path]),s.render(found[0]),path)
                    measured.add((case['kind'],path))
        self.assertEqual(len(measured),22)

    def test_number_and_code_types_follow_xml_owner_modes(self):
        for case in self.cases:
            with self.subTest(phase=case['phase'],kind=case['kind']):
                props=E.fromstring(case['xml'])[0].find(Q+'Properties');paths=forms.object_paths(self.body(case),case['kind'])
                name='Code' if case['kind']=='ChartOfCalculationTypes' else 'Number';key='Object.'+name
                if props.findtext(Q+name+'Length')=='0':self.assertNotIn(key,paths)
                else:self.assertEqual(paths.types[key],'S' if props.findtext(Q+name+'Type')=='String' else 'N')

    def test_description_and_action_period_availability_follow_owner_settings(self):
        for case in self.cases:
            with self.subTest(phase=case['phase'],kind=case['kind']):
                props=E.fromstring(case['xml'])[0].find(Q+'Properties');paths=forms.object_paths(self.body(case),case['kind'])
                if case['kind']!='BusinessProcess':self.assertEqual('Object.Description' in paths,props.findtext(Q+'DescriptionLength')!='0')
                if case['kind']=='ChartOfCalculationTypes':self.assertEqual('Object.ActionPeriodIsBasic' in paths,props.findtext(Q+'ActionPeriodUse')=='true')

    def test_fields_removed_by_owner_settings_cannot_remain_on_form(self):
        pairs=[('no-numbers',k) for k in ('BusinessProcess','Task','ChartOfCalculationTypes')]+[('no-descriptions',k) for k in ('Task','ChartOfCalculationTypes')]
        for phase,kind in pairs:
            with self.subTest(phase=phase,kind=kind),self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
                compiled.validate_form_paths(self.case('default',kind)['form_xml'],self.body(self.case(phase,kind)),kind)
        with self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
            compiled.validate_form_paths(self.case('period','ChartOfCalculationTypes')['form_xml'],self.body(self.case('default','ChartOfCalculationTypes')),'ChartOfCalculationTypes')

    def test_data_version_is_not_a_platform_valid_form_path(self):
        for kind in ('BusinessProcess','Task','ChartOfCalculationTypes'):
            case=self.case('default',kind);key='Object.Code' if kind=='ChartOfCalculationTypes' else 'Object.Number'
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
                compiled.validate_form_paths(case['form_xml'].replace('<DataPath>'+key+'</DataPath>','<DataPath>Object.DataVersion</DataPath>'),self.body(case),kind)

    def test_identical_markers_are_interpreted_in_their_actual_owner_context(self):
        process=forms.object_paths(self.body(self.case('default','BusinessProcess')),'BusinessProcess')
        task=forms.object_paths(self.body(self.case('default','Task')),'Task')
        self.assertEqual(s.render(process['Object.Completed']),s.render(task['Object.BusinessProcess']))
        self.assertEqual(process.types['Object.Completed'],'B');self.assertEqual(task.types['Object.BusinessProcess'],'#')

    def test_ordinary_fields_cannot_shadow_active_standard_fields(self):
        for kind in ('BusinessProcess','Task','ChartOfCalculationTypes'):
            body=copy.deepcopy(self.body(self.case('default',kind)));group=bindings.owners()[kind]['inline_groups'][0]
            body[group['slot']][2][0][1][1][1][2]=s.atom('Code' if kind=='ChartOfCalculationTypes' else 'Number',True)
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'shadows a standard field'):
                forms.object_paths(body,kind)

    def test_native_owner_modes_match_independent_xml_for_all_variants(self):
        for case in self.cases:
            with self.subTest(phase=case['phase'],kind=case['kind']):
                bindings.validate_owner_properties(E.fromstring(case['xml'])[0],self.body(case),case['kind'])

    def test_verified_compiler_misencoding_is_rejected_and_native_export_explains_it(self):
        case=self.mismatch;body=self.body(case);node=E.fromstring(case['xml'])[0]
        with self.assertRaisesRegex(ValueError,'Native owner property differs from XML: BusinessProcess.Autonumbering'):
            bindings.validate_owner_properties(node,body,case['kind'])
        actual=E.fromstring(case['native_export'])[0]
        self.assertEqual(node.findtext(Q+'Properties/'+Q+'Autonumbering'),'false')
        self.assertEqual(actual.findtext(Q+'Properties/'+Q+'Autonumbering'),'true')
        self.assertEqual(node.findtext(Q+'Properties/'+Q+'EditType'),'InDialog')
        self.assertEqual(actual.findtext(Q+'Properties/'+Q+'EditType'),'InList')
        bindings.validate_owner_properties(actual,body,case['kind'])

    def test_compiled_graph_rejects_wrong_native_modes_before_preparing_a_packet(self):
        case=self.mismatch;node=E.fromstring(case['xml'])[0];oid=node.get('uuid')
        record=dict(id=oid,kind=case['kind'],node=node,xml=case['xml'],name=node.findtext(Q+'Properties/'+Q+'Name'),parent_id=s.ZERO)
        with self.assertRaisesRegex(ValueError,'Native owner property differs from XML'):
            graph.TypeIndex({oid:record},{oid:case['body'].encode()}).facts(oid)


if __name__=='__main__':unittest.main()
