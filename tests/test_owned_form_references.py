"""Qualified form references bind to the current owner's registered children."""
import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('flat_object_serializer.py')).parent))
import metadata_serializer as s
import flat_object_serializer as flat
import v8unpack_backend as backend


class OwnedFormReferenceTests(unittest.TestCase):
    def setUp(self):
        self.data=json.loads(Path(__file__).with_name('fixtures').joinpath('owner_form_references_851.json').read_text(encoding='utf-8'))
        self.objects={oid:[s.Parser(text).documents()[0],[s.atom(0)],[s.atom(0)]] for oid,text in self.data['objects'].items()}

    def test_full_owner_bodies_match_independent_native_references(self):
        for case in self.data['cases']:
            with self.subTest(kind=case['kind']):
                body=flat.object_xml(case['xml'],'8.5.1.1529',case['kind'],self.objects)[2]
                self.assertEqual(backend.signature(s.Parser(body.decode('utf-8-sig')).documents()),backend.signature(s.Parser(case['body']).documents()))

    def test_reference_cannot_use_another_owner_with_same_form_name(self):
        for case in self.data['cases']:
            with self.subTest(kind=case['kind']):
                objects=copy.deepcopy(self.objects);owner=objects[case['owner_id']][0]
                fid=s.val(owner[12][1][2]);foreign='77777777-7777-4777-8777-777777777777'
                objects[fid][0][3]=s.atom(foreign)
                with self.assertRaisesRegex(ValueError,'owned form reference'):
                    flat.object_xml(case['xml'],'8.5.1.1529',case['kind'],objects)

    def test_reference_requires_owner_registration(self):
        for case in self.data['cases']:
            objects=copy.deepcopy(self.objects);objects[case['owner_id']][0][12]=[s.atom(0)]
            with self.assertRaisesRegex(ValueError,'owned form reference'):
                flat.object_xml(case['xml'],'8.5.1.1529',case['kind'],objects)

    def test_owned_reference_rejects_wrong_path_and_owner_name(self):
        case=self.data['cases'][0]
        for text in (case['xml'].replace('.Form.','.Unknown.'),case['xml'].replace('DataProcessor.CRSAPI_ProfileProcessor.Form.','DataProcessor.OtherOwner.Form.')):
            with self.assertRaises(ValueError):flat.object_xml(text,'8.5.1.1529',case['kind'],self.objects)


if __name__=='__main__':unittest.main()
