"""Native v47 field upgrade and shared whole-XML conversion rules."""
import copy
import json
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('managed_form_rules.py')).parent))
import metadata_serializer as s
import managed_form_elements as elements
import managed_form_xml as x
import v8unpack_backend as b


class FieldVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=Path(__file__).with_name('fixtures')
        cls.fixture=json.loads((folder/'form_field_versions_851.json').read_text(encoding='utf-8'))
        cls.base=json.loads((folder/'form_rules_851.json').read_text(encoding='utf-8'))
        cls.new=json.loads((folder/'form_new_fields_851.json').read_text(encoding='utf-8'))
        cls.paths=x.ObjectPaths({k:s.Parser(v).documents()[0] for k,v in {**cls.base['paths'],**cls.new['paths']}.items()})
        cls.paths.types={**cls.base['types'],**cls.new['types']};cls.paths.tables=set(cls.base['tables'])

    def test_206_real_fields_keep_all_original_values_during_upgrade(self):
        self.assertEqual(len(self.fixture['cases']),206)
        for case in self.fixture['cases']:
            entry=s.Parser(case['before']).documents()[0];original=copy.deepcopy(entry)
            with self.subTest(kind=case['kind']):
                self.assertEqual(elements.native_kind(elements.FIELD_TYPE,entry,elements.layouts())[0],case['kind'])
                elements.upgrade_field(entry)
                self.assertEqual(s.val(entry[0]),'48')
                self.assertEqual(b.signature(entry[1:-2]),b.signature(original[1:]))
                self.assertEqual([s.val(v) for v in entry[-2:]],['0','0'])
                self.assertEqual(elements.field_header_size(entry),elements.field_header_size(original))

    def test_complete_native_xml_upgrade_oracles_match(self):
        cases=[c for c in self.fixture['cases'] if c['native_xml_upgrade_matches']]
        self.assertEqual(len(cases),101)
        for case in cases:
            entry=s.Parser(case['before']).documents()[0];elements.upgrade_field(entry)
            with self.subTest(kind=case['kind']):
                self.assertEqual(b.signature(entry),b.signature(s.Parser(case['after']).documents()[0]))

    def test_whole_xml_uses_same_rules_for_v47_and_v48(self):
        for kind in ('InputField','CheckBoxField','LabelField','RadioButtonField','ProgressBarField'):
            fixture=self.base if kind in elements.DATA_FIELDS else self.new
            raw=fixture['bases'][kind].encode('utf-8')
            case=next(c for c in fixture['cases'] if c['kind']==kind)
            form=x.interface(raw);index,_,_=elements.form_collection(form);entry=form[1][index+2]
            self.assertEqual([s.val(v) for v in entry[-2:]],['0','0'])
            entry[0]=s.atom(47);del entry[-2:]
            old=b.assemble(b.to_model([form]))
            root=E.fromstring(case['xml']);field=root.find('.//'+x.Q+kind)
            for name in ('ReadOnly','Enabled'):
                previous=field.find(x.Q+name)
                if previous is not None:field.remove(previous)
            E.SubElement(field,x.Q+'ReadOnly').text='true'
            E.SubElement(field,x.Q+'Enabled').text='false'
            xml=E.tostring(root,encoding='unicode')
            convert=lambda source:x.convert(source,xml,paths=self.paths,object_name='CRSAPI_FullCatalog')
            with self.subTest(kind=kind):
                self.assertEqual(b.signature(x.interface(convert(old))),b.signature(x.interface(convert(raw))))

    def test_v48_is_unchanged_and_unknown_versions_or_sizes_fail(self):
        entry=s.Parser(next(c['before'] for c in self.fixture['cases'])).documents()[0]
        elements.upgrade_field(entry);original=b.signature(entry);elements.upgrade_field(entry)
        self.assertEqual(b.signature(entry),original)
        for version in ('46','49'):
            entry[0]=s.atom(version)
            with self.subTest(version=version),self.assertRaises(ValueError):elements.upgrade_field(entry)
        entry[0]=s.atom(47)
        with self.assertRaises(ValueError):elements.upgrade_field(entry)
        entry[0]=s.atom(48);entry.pop()
        with self.assertRaises(ValueError):elements.upgrade_field(entry)


if __name__=='__main__':unittest.main()
