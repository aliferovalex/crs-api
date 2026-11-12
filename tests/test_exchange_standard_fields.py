"""Independent native standard field bindings of exchange plans."""
import base64,copy,json,sys,unittest,zlib
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_metadata as compiled
import native_form_bindings as bindings
import native_form_reader as forms
import native_metadata as s

Q='{http://v8.1c.ru/8.3/MDClasses}';F='{http://v8.1c.ru/8.3/xcf/logform}'
FIELDS={'Ref':(-6,'#'),'DeletionMark':(-4,'B'),'Code':(-2,'S'),'Description':(-3,'S'),'SentNo':(-9,'N'),'ReceivedNo':(-10,'N'),'ThisNode':(-13,'B'),'ExchangeDate':(-14,'D')}


def lists(value):
    if isinstance(value,list):
        yield value
        for child in value:yield from lists(child)


class ExchangeStandardFieldsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('native_exchange_standard_fields.json').read_text())
        cls.data=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))
        cls.cases={c['phase']:c for c in cls.data['cases']}

    def body(self,phase):return s.Parser(self.cases[phase]['body']).documents()[0]

    def test_complete_native_forms_and_properties_validate_in_all_six_modes(self):
        self.assertEqual(set(self.cases),{'default','distributed','no-code','no-description','short-code','long-description'})
        for phase,case in self.cases.items():
            with self.subTest(phase=phase):
                bindings.validate_owner_properties(E.fromstring(case['xml'])[0],self.body(phase),'ExchangePlan')
                compiled.validate_form_interface(case['form_xml'],self.body(phase),'ExchangePlan',case['interface'].encode(),{})

    def test_standard_markers_and_types_equal_independent_native_controls(self):
        for phase,case in self.cases.items():
            paths=forms.object_paths(self.body(phase),'ExchangePlan');native=list(lists(s.Parser(case['interface']).documents()))
            for node in E.fromstring(case['form_xml']).iter():
                name=node.get('name','')
                if name[3:] not in FIELDS or not name.startswith('Std'):continue
                marker,typ=FIELDS[name[3:]];key=node.findtext(F+'DataPath');expected='{2,{1},{'+str(marker)+'}}'
                self.assertEqual(s.render(paths[key]),expected);self.assertEqual(paths.types[key],typ)
                control=next(row for row in native if any(isinstance(v,s.Atom) and v.quoted and s.val(v)==name for v in row))
                self.assertEqual(sum(s.render(row)==expected for row in lists(control)),1)

    def test_all_standard_fields_remain_available_in_native_exports(self):
        for phase in self.cases:
            expected=set(FIELDS)
            paths=forms.object_paths(self.body(phase),'ExchangePlan')
            self.assertEqual({key[7:] for key in paths if key.startswith('Object.')},expected)

    def test_zero_input_lengths_are_normalized_by_platform_and_not_silently_accepted(self):
        for phase in ('no-code','no-description'):
            name='CodeLength' if phase=='no-code' else 'DescriptionLength';source=E.fromstring(self.data['zero_inputs'][phase])[0]
            native=E.fromstring(self.cases[phase]['xml'])[0]
            self.assertEqual(source.findtext(Q+'Properties/'+Q+name),'0')
            self.assertEqual(native.findtext(Q+'Properties/'+Q+name),'9' if phase=='no-code' else '25')
            with self.assertRaisesRegex(ValueError,'Native owner property differs from XML: ExchangePlan.'+name):
                bindings.validate_owner_properties(source,self.body(phase),'ExchangePlan')

    def test_distributed_mode_does_not_change_standard_field_identities(self):
        before=forms.object_paths(self.body('default'),'ExchangePlan');after=forms.object_paths(self.body('distributed'),'ExchangePlan')
        self.assertEqual({k:s.render(v) for k,v in before.items()},{k:s.render(v) for k,v in after.items()})
        self.assertNotIn('Object.DataVersion',before)

    def test_native_modes_must_agree_with_complete_xml(self):
        case=self.cases['default']
        for name,rule in bindings.owners()['ExchangePlan']['native_property_checks'].items():
            body=copy.deepcopy(self.body('default'));parent=bindings.at(body,rule['path'][:-1]);slot=rule['path'][-1];value=s.val(parent[slot]);parent[slot]=s.atom(int(value)+1 if rule.get('integer') else '0' if value=='1' else '1')
            with self.subTest(property=name),self.assertRaisesRegex(ValueError,'Native owner property differs from XML'):
                bindings.validate_owner_properties(E.fromstring(case['xml'])[0],body,'ExchangePlan')


if __name__=='__main__':unittest.main()
