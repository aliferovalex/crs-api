"""Native report parameter defaults must use the active Configuration UUID."""
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('managed_form_operations.py')).parent))
import native_metadata as s
import managed_form_operations as forms
import managed_form_xml as xml
import v8unpack_backend as backend


class ReportFormPropertyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads(Path(__file__).with_name('fixtures').joinpath('report_form_events_851.json').read_text(encoding='utf-8'))

    def test_all_native_interfaces_match_including_different_configuration(self):
        owner=s.Parser(self.data['owner_body']).documents()[0]
        for case in self.data['cases']:
            with self.subTest(case=case['name']):
                _,_,external=forms.create_native('Report',self.data['form_name'],'8.5.1.1529',owner,self.data['definition_xml'],case['form_xml'],case['module_text'],configuration_id=case['configuration_id'])
                self.assertEqual(backend.signature(xml.interface(external)),backend.signature(xml.interface(case['external'].encode('utf-8'))))


if __name__=='__main__':unittest.main()
