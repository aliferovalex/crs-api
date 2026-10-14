"""Native whole-file binary/text payloads and shared packet creation/change."""
import base64
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('template_content.py')).parent))
import template_content as content
import template_serializer as templates
import metadata_serializer as s
from test_catalog_form_serializer import records


class TemplateFileContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=json.loads(Path(__file__).with_name('fixtures').joinpath('template_file_packets_851.json').read_text(encoding='utf-8'))['cases']

    def test_creation_matches_full_native_definition_and_file_stream(self):
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                result=templates.serialize(copy.deepcopy(case['create_request']));_,_,body,external,_,_=records(result)
                self.assertEqual(s.render(s.Parser(body.decode('utf-8-sig')).documents()),s.render(s.Parser(case['create_body']).documents()))
                self.assertEqual(external,base64.b64decode(case['create_external']))

    def test_changes_match_full_native_definition_and_file_stream(self):
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                result=templates.serialize(copy.deepcopy(case['change_request']));raw=s.inflate(base64.b64decode(result['data'])[18:])
                _,pos=s.read_record(raw,0);storage,_=s.read_record(raw,pos+4);s.validate_storage(storage)
                _,pos=s.read_record(storage,12);body,pos=s.read_record(storage,pos);external,_=s.read_record(storage,pos)
                self.assertEqual(s.render(s.Parser(s.inflate(body).decode('utf-8-sig')).documents()),s.render(s.Parser(case['change_body']).documents()))
                self.assertEqual(s.inflate(external),base64.b64decode(case['change_external']))

    def test_companion_preserves_exact_bytes(self):
        for case in self.cases:
            request=case['create_request'];typ=case['kind']
            with self.subTest(kind=typ),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'Metadata.xml';ext=path.with_suffix('')/'Ext';ext.mkdir(parents=True)
                (ext/content.PROFILES[typ]['file']).write_bytes(base64.b64decode(request['template_data']))
                self.assertEqual(content.companion(path,request['definition_xml']),dict(template_data=request['template_data']))
                (ext/content.PROFILES[typ]['file']).unlink()
                with self.assertRaisesRegex(ValueError,'Missing'):content.companion(path,request['definition_xml'])

    def test_binary_empty_and_all_byte_values_roundtrip(self):
        request=next(c['create_request'] for c in self.cases if c['kind']=='BinaryData')
        for data in (b'',bytes(range(256))):
            raw=content.convert(dict(request,template_data=base64.b64encode(data).decode()));content.validate_source(raw,request['definition_xml'])
            token=s.Parser(raw.decode('utf-8-sig')).documents()[0][1][0]
            self.assertEqual(base64.b64decode(''.join(s.val(token)[8:].split())),data)

    def test_text_preserves_bom_unicode_and_line_endings(self):
        request=next(c['create_request'] for c in self.cases if c['kind']=='TextDocument')
        for raw in (b'', 'Привет 📦\r\nстрока\n'.encode('utf-8-sig'), 'Текст без BOM'.encode('utf-8')):
            self.assertEqual(content.convert(dict(request,template_data=base64.b64encode(raw).decode())),raw)
        with self.assertRaisesRegex(ValueError,'UTF-8'):content.convert(dict(request,template_data=base64.b64encode(b'\xff').decode()))


if __name__=='__main__':unittest.main()
