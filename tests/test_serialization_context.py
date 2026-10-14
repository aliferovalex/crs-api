"""Shared snapshot guards and JSON entry points."""
import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as E
import metadata_serializer as s
import serialization_context as context
import serializer_cli
import test_catalog_form_serializer as catalog


class ContextTests(unittest.TestCase):
    def test_matching_snapshot_and_version(self):
        request=catalog.fixture();frame=context.read(request,request['object_id'])
        self.assertEqual(s.val(frame.metadata[1]),request['object_id'])
        self.assertTrue(s.inflate(frame.data))
        self.assertEqual(context.original_version(request['original_version'].upper(),frame.metadata),request['original_version'])

    def test_invalid_base64_and_size(self):
        for value in (None,'!!!'):
            with self.subTest(value=value),self.assertRaises(ValueError):context.decode(value,'Invalid input')
        with patch.object(s,'MAX_BYTES',1),self.assertRaisesRegex(ValueError,'Too large'):
            context.decode('AAAA','Too large')

    def test_mismatching_context_header(self):
        request=catalog.fixture();docs=s.context_metadata(base64.b64decode(request['context']),request['object_id'])
        docs[0][9]=s.atom('AnotherCatalog',True)
        request['context']=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode()
        with self.assertRaisesRegex(ValueError,'Snapshot/context mismatch'):context.read(request,request['object_id'])

    def test_wrong_source_version(self):
        request=catalog.fixture();frame=context.read(request,request['object_id'])
        for value in (None,'x'*40,'f'*40):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'Source version mismatch'):
                context.original_version(value,frame.metadata)


    def test_cli_reports_xml_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'input.json';target=Path(folder)/'output.json'
            source.write_text(json.dumps({'xml':'<unclosed>'}),encoding='utf-8')
            with patch.object(sys,'argv',['serializer',str(source),str(target)]):
                serializer_cli.run(lambda request: {'xml':E.fromstring(request['xml'])})
            result=json.loads(target.read_text(encoding='utf-8'))
            self.assertFalse(result['ok']);self.assertIn('no element found',result['error'])

    def test_configuration_cli_reports_missing_input_file(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'missing.json';target=Path(folder)/'output.json'
            with patch.object(sys,'argv',['metadata_serializer',str(source),str(target)]):
                s.main()
            result=json.loads(target.read_text(encoding='utf-8'))
            self.assertFalse(result['ok']);self.assertIn('missing.json',result['error'])


if __name__=='__main__':unittest.main()
