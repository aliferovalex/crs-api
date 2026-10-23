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
import test_configuration_serializer as metadata
import test_object_creation_serializer as constant
import test_managed_form_operations as forms
import test_metadata_classes as classes
import metadata_context
import metadata_identifiers
import xml_namespaces
import native_metadata as s


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
        result=self.invoke('configuration_serializer',request)
        self.assertTrue(result['ok'],result)
        self.assertEqual(E.fromstring(result['request_xml']).tag,'{'+s.NS+'}call')

    def test_creation_and_inspection_cli_modes_are_preserved(self):
        request=constant.fixture('8.5.1.1529')
        result=self.invoke('object_creation_serializer',request)
        self.assertTrue(result['ok'],result);self.assertEqual(result['object_id'],constant.CID)
        result=self.invoke('object_creation_serializer',dict(request,mode='inspect'))
        self.assertTrue(result['ok'],result);self.assertIn(metadata.CHILD,result['children'])

    def test_external_stream_cli_reads_complete_version_storage(self):
        request=forms.fixture()
        result=self.invoke('external_data',{'storage':request['storage'],'object_id':request['object_id']})
        self.assertTrue(result['ok'],result);self.assertEqual(result['object_id'],forms.FID)
        self.assertEqual(result['externals'][0]['name'],forms.FID+'.0')

    def test_form_cli_routes_creation_and_change_and_rejects_missing_operation(self):
        import test_catalog_form_serializer as creation
        created=self.invoke('managed_form_operations',dict(creation.fixture(),operation='Создание'))
        self.assertTrue(created['ok'],created)
        self.assertEqual(len(created['descriptions']),2)
        changed=self.invoke('managed_form_operations',dict(forms.fixture(),operation='Изменение',module_text='// CLI module'))
        self.assertTrue(changed['ok'],changed)
        self.assertEqual(changed['object_id'],forms.FID)
        rejected=self.invoke('managed_form_operations',forms.fixture())
        self.assertFalse(rejected['ok'])
        self.assertIn('operation',rejected['error'])

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
            q='{'+xml_namespaces.MD+'}'
            top=E.Element(q+'MetaDataObject',version='2.21');obj=E.SubElement(top,q+'Configuration',uuid=metadata.ID)
            name=s.val(metadata_context.context_metadata(base64.b64decode(request['context']),metadata.ID)[0][9])
            E.SubElement(E.SubElement(obj,q+'Properties'),q+'Name').text=name
            children=E.SubElement(obj,q+'ChildObjects')
            objects=metadata_context.context_objects(request['context'])
            for oid,cls in metadata_context.children(objects[metadata.ID][0]):
                label=metadata_identifiers.class_labels().get(cls,'Language')
                if oid not in objects:
                    import copy
                    docs=copy.deepcopy(objects[metadata.ID]);m=docs[0]
                    m[1],m[2],m[3],m[9]=s.atom(oid),s.atom(metadata_identifiers.class_id(label)),s.atom(metadata.ID),s.atom('Language',True)
                    m[12],m[13],m[14]=[s.atom(0)],[s.atom(0)],[s.atom(0)];objects[oid]=docs
                if cls not in metadata_identifiers.class_labels():
                    objects[oid][0][2]=s.atom(metadata_identifiers.class_id(label))
                    for row in objects[metadata.ID][0][12][1:]:
                        if s.val(row[0])==cls:row[0]=objects[oid][0][2]
                E.SubElement(children,q+label).text=s.val(objects[oid][0][9])
            request['context']=base64.b64encode(s.storage([s.text_bytes(d) for d in objects.values()],s.text_bytes([[s.atom(0)]]))).decode()
            xml=Path(folder)/'Configuration.xml';xml.write_text(E.tostring(top,encoding='unicode'),encoding='utf-8')
            result=self.invoke('preparation_plan',{'xml_path':str(xml),'context':request['context'],'options':{}})
            self.assertTrue(result['ok'],result);self.assertEqual(result['kind'],'Configuration')
            self.assertEqual(result['object_id'],metadata.ID)

    def test_json_and_file_errors_use_the_same_cli_contract(self):
        for module in ('configuration_serializer','object_creation_serializer','external_data','metadata_classes','preparation_plan'):
            for options in ({'text':'{'},{'missing':True}):
                with self.subTest(module=module,options=options):
                    result=self.invoke(module,**options)
                    self.assertFalse(result['ok']);self.assertTrue(result['error'])


if __name__=='__main__':unittest.main()
