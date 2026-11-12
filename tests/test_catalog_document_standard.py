"""Native standard fields of catalogs and documents across owner modes."""
import base64,copy,json,sys,unittest,zlib
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_metadata as compiled
import native_form_bindings as bindings
import native_form_reader as forms
import native_metadata as s

Q='{http://v8.1c.ru/8.3/MDClasses}';F='{http://v8.1c.ru/8.3/xcf/logform}'
FIELDS={'Catalog':{'Ref':-8,'DeletionMark':-7,'Code':-2,'Description':-3,'Parent':-4,'IsFolder':-6,'Owner':-5,'Predefined':-10,'PredefinedDataName':-13},'Document':{'Ref':-5,'DeletionMark':-4,'Posted':-7,'Date':-3,'Number':-2}}


def lists(value):
    if isinstance(value,list):
        yield value
        for child in value:yield from lists(child)


class CatalogDocumentStandardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('native_catalog_document_standard.json').read_text())
        cls.cases=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))['cases']

    def case(self,phase,kind):return next(c for c in self.cases if c['phase']==phase and c['kind']==kind)
    def body(self,case):return s.Parser(case['body']).documents()[0]

    def test_complete_native_forms_and_properties_validate_in_all_six_modes(self):
        self.assertEqual({(c['phase'],c['kind']) for c in self.cases},{(phase,kind) for kind in FIELDS for phase in ('default','flat','items','no-owner','no-posting','numeric')})
        for case in self.cases:
            with self.subTest(kind=case['kind'],phase=case['phase']):
                body=self.body(case);bindings.validate_owner_properties(E.fromstring(case['xml'])[0],body,case['kind'])
                compiled.validate_form_interface(case['form_xml'],body,case['kind'],case['interface'].encode(),{})

    def test_every_marker_matches_the_independently_compiled_native_control(self):
        for case in self.cases:
            paths=forms.object_paths(self.body(case),case['kind']);native=list(lists(s.Parser(case['interface']).documents()))
            for node in E.fromstring(case['form_xml']).iter():
                name=node.get('name','')
                if not name.startswith('Std') or name[3:] not in FIELDS[case['kind']]:continue
                expected='{2,{1},{'+str(FIELDS[case['kind']][name[3:]])+'}}';self.assertEqual(s.render(paths[node.findtext(F+'DataPath')]),expected)
                control=next(row for row in native if any(isinstance(v,s.Atom) and v.quoted and s.val(v)==name for v in row))
                self.assertEqual(sum(s.render(row)==expected for row in lists(control)),1)

    def test_catalog_availability_depends_on_hierarchy_kind_and_owner_list(self):
        for case in self.cases:
            if case['kind']!='Catalog':continue
            props=E.fromstring(case['xml'])[0].find(Q+'Properties');expected=set(FIELDS['Catalog'])
            if props.findtext(Q+'Hierarchical')=='false':expected-={'Parent','IsFolder'}
            elif props.findtext(Q+'HierarchyType')=='HierarchyOfItems':expected.remove('IsFolder')
            if not len(props.find(Q+'Owners')):expected.remove('Owner')
            paths=forms.object_paths(self.body(case),'Catalog');self.assertEqual({name for name in FIELDS['Catalog'] if 'Object.'+name in paths},expected)

    def test_disabling_posting_does_not_remove_document_posted_field(self):
        case=self.case('no-posting','Document');self.assertEqual(E.fromstring(case['xml'])[0].findtext(Q+'Properties/'+Q+'Posting'),'Deny')
        paths=forms.object_paths(self.body(case),'Document');self.assertEqual(s.render(paths['Object.Posted']),'{2,{1},{-7}}');self.assertEqual(paths.types['Object.Posted'],'B')

    def test_numeric_code_and_number_keep_marker_and_change_scalar_type(self):
        for kind,name in [('Catalog','Code'),('Document','Number')]:
            before=forms.object_paths(self.body(self.case('default',kind)),kind);after=forms.object_paths(self.body(self.case('numeric',kind)),kind);key='Object.'+name
            self.assertEqual(s.render(before[key]),s.render(after[key]));self.assertEqual(before.types[key],'S');self.assertEqual(after.types[key],'N')

    def test_stale_catalog_paths_are_rejected_after_mode_changes(self):
        for phase in ('flat','items','no-owner'):
            with self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
                compiled.validate_form_paths(self.case('default','Catalog')['form_xml'],self.body(self.case(phase,'Catalog')),'Catalog')

    def test_measured_native_mode_checks_reject_incorrect_compiler_values(self):
        for kind in FIELDS:
            case=self.case('default',kind)
            for name,rule in bindings.owners()[kind]['native_property_checks'].items():
                body=copy.deepcopy(self.body(case));row=bindings.at(body,rule['path'][:-1]);slot=rule['path'][-1];value=s.val(row[slot]);row[slot]=s.atom(int(value)+1 if rule.get('integer') else '0' if value=='1' else '1')
                with self.subTest(kind=kind,property=name),self.assertRaisesRegex(ValueError,'Native owner property differs from XML'):
                    bindings.validate_owner_properties(E.fromstring(case['xml'])[0],body,kind)

    def test_data_version_is_not_in_the_supported_object_paths(self):
        for kind in FIELDS:self.assertNotIn('Object.DataVersion',forms.object_paths(self.body(self.case('default',kind)),kind))


if __name__=='__main__':unittest.main()
