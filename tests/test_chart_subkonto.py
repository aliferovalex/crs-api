"""Subkonto count and real characteristic-plan references use shared rules."""
import copy,json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
import test_document_serializer
import metadata_object_xml as objects,metadata_targets,metadata_identifiers as ids,native_metadata as s


class ChartSubkontoTests(unittest.TestCase):
    def samples(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('chart_subkonto_851.json').read_text(encoding='utf-8'))['samples']
    def targets(self):return metadata_targets.Index(metadata_targets.Target(row['id'],ids.class_id(row['kind']),s.ZERO,s.ZERO,row['name']) for row in self.samples())

    def test_all_complete_native_bodies_and_reverse_xml_match(self):
        for row in self.samples():
            if row['kind']!='ChartOfAccounts':continue
            with self.subTest(case=row['label']):
                raw=objects.create(row['xml'],'8.5.1.1529',row['kind'],objects=self.targets())[2]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(row['body']).documents()))
                xml=objects.export(s.Parser(row['body']).documents()[0],{},'8.5.1.1529',row['kind'],objects=self.targets())
                self.assertEqual(objects.create(E.tostring(xml,encoding='unicode'),'8.5.1.1529',row['kind'],objects=self.targets())[2],raw)

    def test_change_switch_and_clear_links_preserves_all_other_fields(self):
        rows={r['label']:r for r in self.samples() if r['kind']=='ChartOfAccounts'};row=rows['FirstThree'];source=s.Parser(row['body']).documents()[0]
        for label in rows:
            root=E.fromstring(row['xml']);props=root[0].find(objects.Q+'Properties');target=E.fromstring(rows[label]['xml'])[0].find(objects.Q+'Properties');expected=copy.deepcopy(source)
            for key,slot in [('ExtDimensionTypes',19),('MaxExtDimensionCount',20)]:
                props.find(objects.Q+key).text=target.findtext(objects.Q+key);expected[1][slot]=copy.deepcopy(s.Parser(rows[label]['body']).documents()[0][1][slot])
            raw,_=objects.change(E.tostring(root,encoding='unicode'),'8.5.1.1529','ChartOfAccounts',source,reference_objects=self.targets())
            self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()[0]),s.render(expected))

    def test_nonzero_count_requires_a_reference_including_missing_xml_property(self):
        row=next(r for r in self.samples() if r['label']=='FirstOne')
        for missing in (False,True):
            root=E.fromstring(row['xml']);props=root[0].find(objects.Q+'Properties');field=props.find(objects.Q+'ExtDimensionTypes')
            if missing:props.remove(field)
            else:field.text=''
            with self.subTest(missing=missing),self.assertRaisesRegex(ValueError,'Required metadata reference: ExtDimensionTypes'):
                objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','ChartOfAccounts',objects=self.targets())
        root=E.fromstring(row['xml']);root[0].find(objects.Q+'Properties/'+objects.Q+'MaxExtDimensionCount').text='0'
        self.assertEqual(s.val(s.Parser(objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','ChartOfAccounts',objects=self.targets())[2].decode('utf-8-sig')).documents()[0][1][20]),'0')

    def test_missing_ambiguous_and_wrong_class_reference_reject(self):
        row=next(r for r in self.samples() if r['label']=='FirstOne')
        for value in ('ChartOfCharacteristicTypes.Missing','ChartOfAccounts.ProbeDefault','ChartOfCharacteristicType.ProbeFirst'):
            root=E.fromstring(row['xml']);root[0].find(objects.Q+'Properties/'+objects.Q+'ExtDimensionTypes').text=value
            with self.subTest(value=value),self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','ChartOfAccounts',objects=self.targets())
        targets=self.targets();target=next(t for t in targets.targets if t.name=='ProbeFirst');targets=metadata_targets.Index(list(targets.targets)+[target])
        with self.assertRaises(ValueError):objects.create(row['xml'],'8.5.1.1529','ChartOfAccounts',objects=targets)

    def test_reference_alias_matches_the_full_object_profile(self):
        self.assertEqual(objects.profiles.xml_kind('ChartOfCharacteristicType'),'ChartOfCharacteristicTypes')
        self.assertEqual(objects.profiles.profiles()['ChartOfCharacteristicType']['xml_kind'],'ChartOfCharacteristicTypes')

    def test_native_dependencies_use_object_ids_even_when_count_is_zero(self):
        layout=objects.profiles.layout('ChartOfAccounts')
        for row in self.samples():
            if row['kind']!='ChartOfAccounts':continue
            expected={key:flag for key,flag in row['native_relations'].items() if flag!=1}
            self.assertEqual(objects.reference_dependencies(s.Parser(row['body']).documents()[0],layout,row['id']),expected)

    def test_source_dependency_reconciliation_does_not_require_target_full_xml_profile(self):
        import metadata_type_references
        layout=objects.profiles.layout('ChartOfAccounts')
        for row in self.samples():
            if row['kind']!='ChartOfAccounts':continue
            expected={key for key,flag in row['native_relations'].items() if flag==0}
            self.assertEqual(metadata_type_references.source_owners({},s.Parser(row['body']).documents()[0],layout,row['native_relations'],row['id']),expected)

    def test_invalid_counts_reject_and_fifty_one_is_not_artificially_limited(self):
        row=next(r for r in self.samples() if r['label']=='FirstFiftyOne')
        self.assertEqual(s.val(s.Parser(objects.create(row['xml'],'8.5.1.1529','ChartOfAccounts',objects=self.targets())[2].decode('utf-8-sig')).documents()[0][1][20]),'51')
        for value in ('-1','1.5','01','2147483648','bad'):
            root=E.fromstring(row['xml']);root[0].find(objects.Q+'Properties/'+objects.Q+'MaxExtDimensionCount').text=value
            with self.subTest(value=value),self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','ChartOfAccounts',objects=self.targets())
