"""Converters preserve contents and stream versions without assembling packets."""
import base64
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as E

import test_commonmodule_change as modules
import test_managed_form_operations as forms
import test_catalog_form_serializer as new_forms
import test_catalog_creation_full_xml as new_catalog
import commonmodule_serializer
import managed_form_operations
import template_serializer
import object_creation_serializer
import native_content
import configuration_batch
import configuration_commit
import metadata_context
import native_metadata as s
import packet_builder as packets


class NativeContentTests(unittest.TestCase):
    def change_cases(self):
        yield 'CommonModule', modules.fixture(), commonmodule_serializer.compile_change, commonmodule_serializer.serialize_change
        yield 'CatalogForm', forms.fixture(), managed_form_operations.compile_change, managed_form_operations.change
        for filename in ('template_packets_851.json','common_template_packets_851.json'):
            request=json.loads(Path(__file__).with_name('fixtures').joinpath(filename).read_text(encoding='utf-8'))['change']
            yield filename, request, template_serializer.compile_change, template_serializer.change

    def test_changed_contents_match_standalone_packets_without_assembly(self):
        for kind,request,compile,serialize in self.change_cases():
            with self.subTest(kind=kind), patch.object(packets,'external_version',return_value=bytes(range(20))):
                with patch.object(packets,'assemble',side_effect=AssertionError('Intermediate packet')):
                    content=compile(copy.deepcopy(request))
                self.assertIsInstance(content,native_content.ObjectContent)
                source=metadata_context.context_metadata(base64.b64decode(request['context']),request['object_id'])
                self.assertEqual(s.val(content.docs[0][0]),s.val(source[0][0]))
                self.assertEqual(s.val(content.docs[0][7]),s.val(source[0][7]))
                _,records=configuration_batch.read_packet(serialize(copy.deepcopy(request))['data'])
                self.assertEqual(len(records),1)
                record=records[0]
                self.assertEqual(content.body,s.inflate(record.body))
                self.assertEqual(content.streams,list(record.externals))
                metadata=s.Parser(record.metadata.decode('utf-8-sig')).documents()
                self.assertEqual(s.render(content.docs[0][11]),s.render(metadata[0][11]))
                self.assertEqual(s.render(content.docs[2]),s.render(metadata[2]))
                self.assertEqual(content.externals,[dict(name=content.streams[0][0],version=bytes(range(20)).hex(),action=1)])

    def test_common_module_complete_export_uses_direct_converter(self):
        request=modules.fixture();oid=request['object_id']
        # Match the complete-file contract of the folder entry point.
        import test_commonmodule_serializer as source
        change=dict(object_id=oid,kind='CommonModule',object_xml=source.xml(),module_text=request['source_text'])
        request.update(originals={oid:request['original_version']},snapshots={oid:request['snapshot']})
        with patch.object(packets,'assemble',side_effect=AssertionError('Intermediate packet')):
            content=configuration_commit.content(request,change,metadata_context.context_objects(request['context']))
        self.assertIsInstance(content,native_content.ObjectContent)
        self.assertEqual(content.streams[0][0],oid+'.0')

    def test_creation_contents_keep_forms_and_module_streams_without_assembly(self):
        request=new_catalog.forms_request()
        with patch.object(packets,'assemble',side_effect=AssertionError('Intermediate packet')):
            result=object_creation_serializer.serialize(request,contents_only=True)
        self.assertIsInstance(result,native_content.CreationContent)
        self.assertEqual(len(result.objects),1+len(request['forms']))
        expected=[E.fromstring(form['definition_xml'])[0].get('uuid') for form in request['forms']]
        expected.append(E.fromstring(request['object_xml'])[0].get('uuid'))
        self.assertEqual(list(result.objects),expected)
        for oid,content in result.objects.items():
            self.assertIsInstance(content,native_content.ObjectContent)
            self.assertEqual(s.val(content.docs[0][1]),oid)
            self.assertTrue(content.body)
            self.assertEqual([name for name,_ in content.streams],[entry['name'] for entry in content.externals if entry['action'] in (0,1)])

    def test_owned_form_creation_excludes_owner_packet(self):
        request=new_forms.fixture()
        with patch.object(packets,'assemble',side_effect=AssertionError('Intermediate packet')):
            result=managed_form_operations.create(request,contents_only=True)
        self.assertEqual(len(result.objects),1)
        oid,content=next(iter(result.objects.items()))
        self.assertNotEqual(oid,request['object_id'])
        self.assertEqual(s.val(content.docs[0][3]),request['object_id'])
        self.assertEqual(content.streams[0][0],oid+'.0')


if __name__=='__main__':unittest.main()
