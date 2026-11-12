"""Measured standard PVR tables, structured links and compiler fidelity limits."""
import base64,copy,json,re,sys,unittest,zlib
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_dependencies as deps
import compiled_graph as graph
import compiled_metadata as compiled
import export_coverage
import native_form_reader as forms
import native_metadata as s
import native_predefined_reader as predefined
import xml_compare

Q='{http://v8.1c.ru/8.3/MDClasses}'
F='{http://v8.1c.ru/8.3/xcf/logform}'
P='{http://v8.1c.ru/8.3/xcf/predef}'
KIND='ChartOfCalculationTypes'
TABLES=('BaseCalculationTypes','DisplacingCalculationTypes','LeadingCalculationTypes')


def lists(value):
    if isinstance(value,list):
        yield value
        for child in value:yield from lists(child)


class PVRStandardTablesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('native_pvr_standard_tables.json').read_text(encoding='utf-8'))
        cls.data=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))
        cls.cases={case['phase']:case for case in cls.data['cases']}

    def body(self,case):return s.Parser(case['body']).documents()[0]

    def inputs(self,case):
        records={row['id']:dict(row,node=E.fromstring(row['xml'])[0]) for row in case['records']}
        return records,{name:raw.encode() for name,raw in case['image'].items()}

    def test_whole_native_forms_validate_in_every_mode(self):
        for phase,case in self.cases.items():
            with self.subTest(phase=phase):
                compiled.validate_form_interface(case['form_xml'],self.body(case),KIND,case['interface'].encode(),{})

    def test_table_and_column_paths_equal_independent_native_bindings(self):
        case=self.cases['line-numbers'];paths=forms.object_paths(self.body(case),KIND)
        native=list(lists(s.Parser(case['interface']).documents()))
        for control in E.fromstring(case['form_xml']).iter():
            path=control.findtext(F+'DataPath');name=control.get('name')
            if not path or not any(path.startswith('Object.'+table) for table in TABLES):continue
            rows=[row for row in native if any(isinstance(v,s.Atom) and v.quoted and s.val(v)==name for v in row)]
            self.assertEqual(len(rows),1,name)
            own=[row for row in lists(rows[0]) if s.render(row)==s.render(paths[path])]
            self.assertEqual(len(own),1,path)
        for table in TABLES:
            self.assertIn('Object.'+table,paths.tables)
            self.assertEqual(paths.types['Object.'+table+'.LineNumber'],'N')
            self.assertEqual(paths.types['Object.'+table+'.CalculationType'],'#')

    def test_availability_depends_on_native_owner_modes(self):
        for phase,case in self.cases.items():
            with self.subTest(phase=phase):
                props=E.fromstring(case['xml'])[0].find(Q+'Properties');paths=forms.object_paths(self.body(case),KIND)
                expected={'LeadingCalculationTypes'}
                if props.findtext(Q+'DependenceOnCalculationTypes')!='DontUse':expected.add('BaseCalculationTypes')
                if props.findtext(Q+'ActionPeriodUse')=='true':expected.add('DisplacingCalculationTypes')
                self.assertEqual({table for table in TABLES if 'Object.'+table in paths.tables},expected)
                for table in TABLES:
                    for column in ('LineNumber','CalculationType'):
                        self.assertEqual('Object.'+table+'.'+column in paths,table in expected)

    def test_unavailable_tables_and_their_columns_cannot_stay_on_form(self):
        name=E.fromstring(self.cases['enabled']['xml'])[0].findtext(Q+'Properties/'+Q+'Name')
        for phase,table in [('independent','BaseCalculationTypes'),('leading-only','BaseCalculationTypes'),('leading-only','DisplacingCalculationTypes')]:
            for suffix in ('','.CalculationType','.LineNumber'):
                xml='<Form xmlns="'+F[1:-1]+'" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config"><Attributes><Attribute name="Object" id="1"><MainAttribute>true</MainAttribute><Type><v8:Type>cfg:ChartOfCalculationTypesObject.'+name+'</v8:Type></Type></Attribute></Attributes><ChildItems><Table name="Table" id="1"><DataPath>Object.'+table+suffix+'</DataPath></Table></ChildItems></Form>'
                with self.subTest(phase=phase,table=table,suffix=suffix),self.assertRaisesRegex(ValueError,'unavailable final DataPath'):
                    compiled.validate_form_paths(xml,self.body(self.cases[phase]),KIND)

    def test_native_links_resolve_plan_owners_and_add_cross_plan_dependency(self):
        for phase in ('linked','cross-linked','leading-cross-linked'):
            case=self.cases[phase];records,image=self.inputs(case);node=E.fromstring(case['xml'])[0];oid=node.get('uuid');index=graph.TypeIndex(records,image)
            with self.subTest(phase=phase):
                refs=predefined.calculation_references(case['predefined'].encode())
                self.assertTrue(refs<=records.keys());self.assertIn(oid,refs)
                other={key for key,row in records.items() if row['kind']==KIND and key!=oid}
                if phase!='linked':self.assertEqual(refs-{oid},other)
                dependencies=deps.references(index,records[oid],image[oid],image,case['xml'])
                self.assertNotIn(oid,dependencies)
                for key in other:self.assertEqual(dependencies[key],0)
                self.assertEqual(set(predefined.read(case['predefined'].encode(),KIND)),{'Main','BaseA','DisplacedA','LeadingA'})

    def test_malformed_compiler_rows_are_rejected_even_with_present_xml(self):
        case=self.cases['linked'];records,image=self.inputs(case);oid=E.fromstring(case['xml'])[0].get('uuid')
        bad=self.data['invalid_compiled_predefined'].encode();image[oid+'.2']=bad
        with self.assertRaisesRegex(ValueError,'requires plan and value columns'):predefined.read(bad,KIND)
        path='ChartsOfCalculationTypes/CRSFormOwnerChartOfCalculationTypes/Ext/Predefined.xml'
        owned={oid:records[oid]};streams={oid+'.2':bad}
        with self.assertRaisesRegex(ValueError,'requires plan and value columns'):
            export_coverage.require_complete_export(streams,owned,{path:self.data['compiled_predefined_xml'].encode()})

    def test_known_named_block_order_is_equivalent_without_ignoring_contents(self):
        native=self.cases['linked']['predefined_xml'];exported=self.data['compiled_predefined_xml']
        self.assertTrue(xml_compare.file_equal('Ext/Predefined.xml',native.encode(),exported.encode()))
        changed=exported.replace('.BaseA</CalculationType>','.LeadingA</CalculationType>')
        self.assertFalse(xml_compare.file_equal('Ext/Predefined.xml',native.encode(),changed.encode()))

    def test_row_order_and_unrelated_xml_remain_significant(self):
        prefix='<PredefinedData xmlns="'+P[1:-1]+'" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="CalculationTypePredefinedItems"><Item>'
        left=prefix+'<Base><CalculationType>A</CalculationType><CalculationType>B</CalculationType></Base></Item></PredefinedData>'
        right=left.replace('<CalculationType>A</CalculationType><CalculationType>B</CalculationType>','<CalculationType>B</CalculationType><CalculationType>A</CalculationType>')
        self.assertNotEqual(xml_compare.document(left),xml_compare.document(right))
        first='<Root><Item><Base/><Leading/></Item></Root>';last='<Root><Item><Leading/><Base/></Item></Root>'
        self.assertNotEqual(xml_compare.document(first),xml_compare.document(last))

    def test_duplicate_named_sections_are_not_normalized(self):
        xml='<PredefinedData xmlns="'+P[1:-1]+'" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="CalculationTypePredefinedItems"><Item><Base/><Base/></Item></PredefinedData>'
        with self.assertRaisesRegex(ValueError,'Duplicate predefined calculation section'):xml_compare.document(xml)

    def test_xml_space_preserve_keeps_named_section_order(self):
        xml='<PredefinedData xmlns="'+P[1:-1]+'" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="CalculationTypePredefinedItems" xml:space="preserve"><Item><Base/><Leading/></Item></PredefinedData>'
        self.assertNotEqual(xml_compare.document(xml),xml_compare.document(xml.replace('<Base/><Leading/>','<Leading/><Base/>')))


if __name__=='__main__':unittest.main()
