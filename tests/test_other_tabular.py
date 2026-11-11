"""Native tabular collections and managed bindings for the remaining CF owners."""
import base64,copy,json,sys,unittest,zlib
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_graph as graph
import compiled_metadata as compiled
import native_form_reader as forms
import native_metadata as s
import native_tabular as tabular
import metadata_structure


class OtherTabularTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('native_other_tabular.json').read_text(encoding='utf-8'))
        cls.cases=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))['cases']

    def body(self,case,field='body'):return s.Parser(case[field]).documents()[0]

    def test_reader_profiles_cover_all_configuration_tabular_owners(self):
        owners={row['runtime_name'] for row in metadata_structure.classes().values()
                if row['xml_name'] not in ('ExternalDataProcessor','ExternalReport')
                and any(c['item_type']=='TabularSection' for c in row['collections'])}
        self.assertEqual(set(tabular.kinds()),owners)

    def test_whole_native_form_accepts_main_type_table_and_four_columns(self):
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                body=self.body(case)
                compiled.validate_form_interface(case['form_xml'],body,case['kind'],case['interface'].encode(),{})
                paths=forms.object_paths(body,case['kind'])
                self.assertEqual(paths.tables,{'Object.Rows'})
                for name,code in [('Text','S'),('Quantity','N'),('Active','B'),('Moment','D')]:
                    self.assertEqual(paths.types['Object.Rows.'+name],code)

    def test_section_and_attribute_identities_match_independent_xml(self):
        q='{http://v8.1c.ru/8.3/MDClasses}'
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                body=self.body(case);part,=tabular.collection(body,case['kind'])
                xml_part=next(E.fromstring(case['xml']).iter(q+'TabularSection'))
                expected=[node.get('uuid') for node in xml_part.iter() if node.get('uuid')]
                self.assertEqual(tabular.feature_ids(part),expected)
                self.assertEqual(len(expected),5)
                for node in xml_part.iter():
                    if node.get('uuid'):graph.common_identity(body,node.get('uuid'),node.findtext(q+'Properties/'+q+'Name'))

    def test_table_binding_rejects_owner_from_before_section_creation(self):
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                body=self.body(case,'before')
                self.assertEqual(tabular.collection(body,case['kind']),[])
                self.assertFalse(forms.object_paths(body,case['kind']).tables)
                with self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
                    compiled.validate_form_paths(case['form_xml'],body,case['kind'])

    def test_collection_class_and_count_cannot_be_reinterpreted(self):
        for case in self.cases:
            for slot,value in [(0,s.atom(s.ZERO)),(1,s.atom(0))]:
                with self.subTest(kind=case['kind'],slot=slot):
                    body=copy.deepcopy(self.body(case));body[tabular.layout(case['kind']).get('slot',5)][slot]=value
                    with self.assertRaisesRegex(ValueError,'Unsupported tabular section collection'):
                        forms.object_paths(body,case['kind'])

    def test_native_main_type_must_belong_to_the_actual_owner(self):
        other=self.cases[-1]
        for case in self.cases[:-1]:
            with self.subTest(kind=case['kind']),self.assertRaisesRegex(ValueError,'main attribute type differs'):
                compiled.validate_form_interface(other['form_xml'],self.body(case),case['kind'],other['interface'].encode(),{})


if __name__=='__main__':unittest.main()
