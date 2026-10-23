"""Shared snapshot guards and JSON entry points."""
import base64
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import configuration_serializer
import metadata_context
import native_metadata as s
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
        request=catalog.fixture();docs=metadata_context.context_metadata(base64.b64decode(request['context']),request['object_id'])
        docs[0][9]=s.atom('AnotherCatalog',True)
        request['context']=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode()
        with self.assertRaisesRegex(ValueError,'Snapshot/context mismatch'):context.read(request,request['object_id'])

    def test_mismatch_diagnostic_identifies_fields_without_dumping_values(self):
        request=catalog.fixture();frame=context.read(request,request['object_id'])
        changed=list(frame.metadata)
        changed[9]=s.atom('Private object label',True)
        changed[10]=s.atom(413)
        with self.assertRaises(ValueError) as failure:
            context.validate_metadata(frame.saved[0],changed,request['object_id'])
        message=str(failure.exception)
        self.assertIn(request['object_id'],message)
        self.assertIn('fields=9,10',message)
        self.assertNotIn('Private object label',message)

    def test_stream_order_is_irrelevant_but_versions_and_membership_are_strict(self):
        request=catalog.fixture();frame=context.read(request,request['object_id'])
        first='11111111-1111-4111-8111-111111111111';second='22222222-2222-4222-8222-222222222222'
        saved=copy.deepcopy(frame.metadata)
        saved[11]=s.Parser('{2,"object.0",'+first+',"object.2",'+second+'}').documents()[0]
        current=copy.deepcopy(saved)
        current[11]=s.Parser('{2,"object.2",'+second+',"object.0",'+first+'}').documents()[0]
        context.validate_metadata(saved,current,request['object_id'])
        invalid=['{1,"object.0",'+first+'}',
                 '{2,"object.0",'+first+',"object.2",'+first+'}',
                 '{2,"object.0",'+first+',"object.0",'+second+'}',
                 '{9,"object.0",'+first+'}',
                 '{1,"object.0",invalid-version}']
        for value in invalid:
            changed=copy.deepcopy(saved);changed[11]=s.Parser(value).documents()[0]
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'Snapshot/context mismatch'):
                context.validate_metadata(saved,changed,request['object_id'])

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
            with patch.object(sys,'argv',['configuration_serializer',str(source),str(target)]):
                configuration_serializer.main()
            result=json.loads(target.read_text(encoding='utf-8'))
            self.assertFalse(result['ok']);self.assertIn('missing.json',result['error'])


if __name__=='__main__':unittest.main()
