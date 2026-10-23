"""Native numerator classes use the XML alias and shared object/reference path."""
import json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
import test_document_serializer
import metadata_object_xml as objects
import metadata_targets
import metadata_identifiers as ids
import native_metadata as s


class DocumentNumeratorTests(unittest.TestCase):
    def samples(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('document_numerators_851.json').read_text(encoding='utf-8'))['samples']
    def targets(self):return metadata_targets.Index(metadata_targets.Target(row['id'],ids.class_id(row['kind']),s.ZERO,s.ZERO,row['name']) for row in self.samples())

    def test_all_full_native_bodies_and_xml_roundtrip(self):
        for case in self.samples():
            with self.subTest(case=case['label']):
                raw=objects.create(case['xml'],'8.5.1.1529',case['kind'],objects=self.targets())[2]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))
                xml=objects.export(s.Parser(case['body']).documents()[0],{},'8.5.1.1529',case['kind'],objects=self.targets())
                self.assertEqual(xml[0].tag,objects.Q+objects.profiles.xml_kind(case['kind']))
                self.assertEqual(objects.create(E.tostring(xml,encoding='unicode'),'8.5.1.1529',case['kind'],objects=self.targets())[2],raw)

    def test_whole_numerator_changes_preserve_identity(self):
        cases=[row for row in self.samples() if row['kind']=='DocumentNumerators'];base=cases[0];source=s.Parser(base['body']).documents()[0]
        for case in cases[1:]:
            root=E.fromstring(case['xml']);root[0].set('uuid',base['id']);root[0].find(objects.Q+'Properties/'+objects.Q+'Name').text=base['name']
            raw,_=objects.change(E.tostring(root,encoding='unicode'),'8.5.1.1529','DocumentNumerators',source)
            expected=s.Parser(case['body'].replace(case['id'],base['id'])).documents()[0];expected[1][1][2]=s.atom(base['name'],True)
            self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()[0]),s.render(expected))

    def test_change_and_clear_numerator_reference(self):
        cases={row['label']:row for row in self.samples()};case=cases['DocumentDefault'];source=s.Parser(case['body']).documents()[0]
        for value,expected in [('DocumentNumerator.ProbeYear',cases['Year']['id']),('',s.ZERO)]:
            root=E.fromstring(case['xml']);root[0].find(objects.Q+'Properties/'+objects.Q+'Numerator').text=value
            raw,_=objects.change(E.tostring(root,encoding='unicode'),'8.5.1.1529','Document',source,reference_objects=self.targets())
            self.assertEqual(s.val(s.Parser(raw.decode('utf-8-sig')).documents()[0][1][10]),expected)

    def test_missing_reference_or_native_class_spelling_in_xml_rejects(self):
        case=next(row for row in self.samples() if row['kind']=='Document');root=E.fromstring(case['xml'])
        for value in ('DocumentNumerator.Missing','DocumentNumerators.ProbeDefault'):
            root[0].find(objects.Q+'Properties/'+objects.Q+'Numerator').text=value
            with self.subTest(value=value),self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','Document',objects=self.targets())
        case=self.samples()[0]
        with self.assertRaises(ValueError):objects.allocate_creation(case['xml'].replace('DocumentNumerator','DocumentNumerators'),'8.5.1.1529','DocumentNumerators')

    def test_creation_declaration_uses_xml_alias(self):
        case=self.samples()[0];decl=objects.allocate_creation(case['xml'],'8.5.1.1529','DocumentNumerators')
        self.assertEqual((decl.object_id,decl.name,decl.generated),(case['id'],case['name'],()))

    def test_reference_flag_matches_independent_native_repository_descriptors(self):
        rule=objects.profiles.layout('Document')['reference_values']['Numerator']
        for case in self.samples():
            if case['kind']!='Document':continue
            self.assertEqual(case['native_relations'][case['numerator_id']],rule.get('relation_flag',0))

    def test_unknown_values_reject(self):
        case=self.samples()[0]
        for key,value in [('NumberType','Unknown'),('NumberPeriodicity','Unknown'),('NumberLength','-1'),('CheckUnique','yes')]:
            root=E.fromstring(case['xml']);root[0].find(objects.Q+'Properties/'+objects.Q+key).text=value
            with self.subTest(property=key),self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','DocumentNumerators')
