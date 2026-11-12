"""Whole-response validation for the opt-in addressed XML reader."""
import base64
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/Сериализация'))
import file_exchange as exchange

TARGET='bfafe7af-773f-43fb-9200-bf73396fd15c'
NS=exchange.NS
def reply(body):return '<call_return xmlns="'+NS+'">'+body+'</call_return>'
def row(oid=TARGET,version='343'):
    return '<value><first value="'+oid+'"/><second><verNum value="'+version+'"/><revised value="true"/><revisorID value="00000000-0000-0000-0000-000000000000"/><reviseDate value="2026-09-30T14:00:15"/></second></value>'

class StatisticsXmlTests(unittest.TestCase):
    def read(self,text,target=TARGET):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'reply.xml';path.write_text(text,encoding='utf-8')
            return exchange.inspect_xml(path,target)

    def test_selects_last_entry_in_full_map_and_preserves_lock_fields(self):
        result=self.read(reply('<statMap>'+row('11111111-1111-4111-8111-111111111111')*53866+row()+'</statMap>'))
        self.assertTrue(result['found']);self.assertEqual(result['state']['version'],343)
        self.assertTrue(result['state']['captured']);self.assertEqual(result['state']['capture_date'],'2026-09-30T14:00:15')

    def test_rejects_duplicate_target_in_same_or_separate_entries(self):
        for body in [row()+row(),row().replace('<first value="'+TARGET+'"/>',('<first value="'+TARGET+'"/>')*2)]:
            with self.subTest(body=body),self.assertRaisesRegex(ValueError,'Duplicate'):
                self.read(reply('<statMap>'+body+'</statMap>'))

    def test_rejects_tail_exception_foreign_namespace_and_malformed_xml(self):
        good=reply('<statMap>'+row()+'</statMap>')
        for text in [good.replace('</call_return>','<exc>ZXJyb3I=</exc></call_return>'),good+'<broken',good.replace('<statMap>','<statMap xmlns="urn:other">'),good[:-5],'<call_exception xmlns="'+NS+'">ZXJyb3I=</call_exception>', '<!DOCTYPE x [<!ENTITY e "x">]>'+good]:
            with self.subTest(text=text),self.assertRaises(ValueError):self.read(text)

    def test_missing_target_and_missing_version_stay_distinct(self):
        self.assertFalse(self.read(reply('<statMap/>'))['found'])
        result=self.read(reply('<statMap>'+row().replace('<verNum value="343"/>','')+'</statMap>'))
        self.assertTrue(result['found']);self.assertIsNone(result['state']['version'])

    def test_validation_only_accepts_utf8_and_checks_the_tail(self):
        self.assertFalse(self.read(reply('<name value="РусскоеИмя"/>'),None)['found'])
        with self.assertRaisesRegex(ValueError,'error'):
            self.read(reply('<name value="РусскоеИмя"/><exception>ZXJyb3I=</exception>'),None)

    def test_empty_exception_before_statistics_does_not_change_selection(self):
        self.assertEqual(self.read(reply('<exc/><statMap>'+row()+'</statMap>'))['state']['version'],343)

    def test_namespace_uri_prefix_is_not_the_protocol_namespace(self):
        with self.assertRaises(ValueError):
            self.read(reply('<statMap xmlns="'+NS+'|foreign">'+row()+'</statMap>'))

if __name__=='__main__':unittest.main()
