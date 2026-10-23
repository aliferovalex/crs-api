"""Historical regression witnesses, with native-verified tabular correction."""
import base64
import json
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as E

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'Сериализация'))
import metadata_object_xml as objects
import native_metadata as native


class UnifiedObjectXmlTests(unittest.TestCase):
    def cases(self):
        cases=json.loads((ROOT / 'tests' / 'fixtures' / 'unified_object_xml.json').read_text(encoding='utf-8'))
        # Old Python witnesses mistakenly treated tabular fields as ordinary
        # attributes with FillValue. Designer has no such tabular XML property;
        # metadata_reference_types_851.json verifies the corrected native body.
        for case in cases:
            if case['kind']!='Catalog':continue
            top=E.fromstring(case['xml']);raw=base64.b64decode(case['body']).decode('utf-8-sig')
            body=native.Parser(raw).documents()[0];patches=[]
            for section in top[0].findall(objects.Q+'ChildObjects/'+objects.Q+'TabularSection'):
                for props in section.findall(objects.Q+'ChildObjects/'+objects.Q+'Attribute/'+objects.Q+'Properties'):
                    for name in ('FillValue','FillFromFillingValue'):
                        node=props.find(objects.Q+name)
                        if node is not None:props.remove(node)
            for section in body[5][2:]:
                for attr in section[2][2:]:
                    value=attr[0][1][19]
                    patches.append((value.start,value.end,'{"S",""}'))
            for start,end,value in sorted(patches,reverse=True):raw=raw[:start]+value+raw[end:]
            case['xml']=E.tostring(top,encoding='unicode');case['body']=base64.b64encode(b'\xef\xbb\xbf'+raw.encode('utf-8')).decode()
        return cases

    def test_unified_creation_preserves_corrected_regression_native_bytes(self):
        for case in self.cases():
            with self.subTest(case=case['name']):
                _, _, body, generated = objects.create(case['xml'], case['platform'], case['kind'], case['forms'])
                self.assertEqual(body, base64.b64decode(case['body']))
                self.assertEqual(set(generated), set(case['generated']))

    def test_shared_export_round_trips_complete_objects(self):
        for case in self.cases():
            with self.subTest(case=case['name']):
                expected = base64.b64decode(case['body'])
                source = native.Parser(expected.decode('utf-8-sig')).documents()[0]
                tree = objects.export(source, case['forms'], case['platform'], case['kind'])
                _, _, actual, _ = objects.create(E.tostring(tree, encoding='unicode'), case['platform'], case['kind'], case['forms'])
                self.assertEqual(actual, expected)

    def test_export_does_not_silently_discard_unknown_native_fields(self):
        case = next(row for row in self.cases() if row['kind'] == 'Catalog' and not row['forms'])
        source = native.Parser(base64.b64decode(case['body']).decode('utf-8-sig')).documents()[0]
        common=objects.at(source,objects.common_path(objects.profiles.layout('Catalog',case['platform'])))
        common[5]=native.atom(1)  # An unmapped common metadata flag must be preserved or rejected.
        with self.assertRaisesRegex(ValueError, 'export profile'):
            objects.export(source, {}, case['platform'], case['kind'])


if __name__ == '__main__':
    unittest.main()
