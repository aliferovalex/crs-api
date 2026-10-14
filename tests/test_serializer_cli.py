"""Actual JSON subprocess entry points, without repository access."""
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as E
import test_metadata_serializer as metadata
import test_constant_serializer as constant
import test_managed_form_change as forms
import test_metadata_classes as classes
import metadata_serializer as s


class SerializerCliTests(unittest.TestCase):
    def invoke(self, module, request=None, text=None, missing=False):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'input.json';target=Path(folder)/'output.json'
            if not missing:
                source.write_text(text if text is not None else json.dumps(request,ensure_ascii=False),encoding='utf-8')
            result=subprocess.run([sys.executable,str(Path(s.__file__).with_name(module+'.py')),str(source),str(target)],
                                  capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr.decode('utf-8',errors='replace'))
            return json.loads(target.read_text(encoding='utf-8'))

    def test_root_cli_keeps_ast_identity_and_returns_commit_request(self):
        request,_=metadata.property_fixture('8.5.1.1529')
        request['after_xml']=request['before_xml'].replace('<Comment>До</Comment>','<Comment>CLI</Comment>')
        result=self.invoke('metadata_serializer',request)
        self.assertTrue(result['ok'],result)
        self.assertEqual(E.fromstring(result['request_xml']).tag,'{'+s.NS+'}call')

    def test_creation_and_inspection_cli_modes_are_preserved(self):
        request=constant.fixture('8.5.1.1529')
        result=self.invoke('constant_serializer',request)
        self.assertTrue(result['ok'],result);self.assertEqual(result['object_id'],constant.CID)
        result=self.invoke('constant_serializer',dict(request,mode='inspect'))
        self.assertTrue(result['ok'],result);self.assertIn(metadata.CHILD,result['children'])

    def test_external_stream_cli_reads_complete_version_storage(self):
        request=forms.fixture()
        result=self.invoke('external_data',{'storage':request['storage'],'object_id':request['object_id']})
        self.assertTrue(result['ok'],result);self.assertEqual(result['object_id'],forms.FID)
        self.assertEqual(result['externals'][0]['name'],forms.FID+'.0')

    def test_class_discovery_cli_preserves_result_with_ok_field(self):
        request,_=metadata.property_fixture('8.5.1.1529')
        meta,_=s.read_record(base64.b64decode(request['snapshot']),12)
        root=classes.root();root[1][0]=s.atom(metadata.ID)
        data=s.compress(s.text_bytes([root]))
        manifest=s.text_bytes([[s.atom(0),s.atom(1),s.atom(metadata.ID),s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(data).hexdigest(),True),s.atom(0)]])
        request['snapshot']=base64.b64encode(s.storage([meta,data],manifest)).decode()
        result=self.invoke('metadata_classes',request)
        self.assertTrue(result['ok'],result);self.assertEqual(len(result['classes']),3)

    def test_preparation_cli_resolves_configuration_xml(self):
        request,_=metadata.property_fixture('8.5.1.1529')
        with tempfile.TemporaryDirectory() as folder:
            q='{'+constant.c.MD+'}'
            top=E.Element(q+'MetaDataObject',version='2.21');obj=E.SubElement(top,q+'Configuration',uuid=metadata.ID)
            name=s.val(s.context_metadata(base64.b64decode(request['context']),metadata.ID)[0][9])
            E.SubElement(E.SubElement(obj,q+'Properties'),q+'Name').text=name
            xml=Path(folder)/'Configuration.xml';xml.write_text(E.tostring(top,encoding='unicode'),encoding='utf-8')
            result=self.invoke('preparation_plan',{'xml_path':str(xml),'context':request['context'],'options':{}})
            self.assertTrue(result['ok'],result);self.assertEqual(result['kind'],'Configuration')
            self.assertEqual(result['object_id'],metadata.ID)

    def test_json_and_file_errors_use_the_same_cli_contract(self):
        for module in ('metadata_serializer','constant_serializer','external_data','metadata_classes','preparation_plan'):
            for options in ({'text':'{'},{'missing':True}):
                with self.subTest(module=module,options=options):
                    result=self.invoke(module,**options)
                    self.assertFalse(result['ok']);self.assertTrue(result['error'])


if __name__=='__main__':unittest.main()
