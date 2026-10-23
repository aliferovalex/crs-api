"""Whole-export name changes retain opaque external contents and their versions."""
import base64,copy,json,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as E
import test_commonmodule_change as module_cases
import test_managed_form_operations as form_cases
from test_managed_form_creation import store
import commonmodule_serializer as modules
import managed_form_operations as forms
import metadata_context,metadata_object_xml as objects,native_metadata as s
import template_serializer as templates,xml_namespaces


class DefinitionRenameTests(unittest.TestCase):
    def test_all_eighteen_definition_bodies_match_independent_native_renames(self):
        import form_definition_xml
        cases=json.loads(Path(__file__).with_name('fixtures').joinpath('definition_rename_851.json').read_text(encoding='utf-8'))['samples']
        self.assertEqual(len(cases),18)
        for case in cases:
            with self.subTest(kind=case['kind'],name=case['old_name']):
                source=case['source'].encode('utf-8-sig')
                if case['kind']=='CommonModule':raw,_=objects.change(case['xml'],'8.5.1.1529','CommonModule',s.Parser(case['source']).documents()[0],allow_rename=True)
                elif case['kind'] in ('Form','CommonForm'):raw=form_definition_xml.convert(source,case['xml'],'Catalog' if case['kind']=='Form' else 'CommonForm','8.5.1.1529',allow_rename=True)
                else:raw=templates.native_definition(case['xml'],'8.5.1.1529')[2]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))

    def renamed(self,text,name='Renamed'):
        root=E.fromstring(text);root[0].find(objects.Q+'Properties/'+objects.Q+'Name').text=name
        return xml_namespaces.render(root,text)

    def module(self):
        request=module_cases.fixture();raw=base64.b64decode(request['snapshot']);_,pos=s.read_record(raw,12);body,_=s.read_record(raw,pos)
        source=s.Parser(s.inflate(body).decode('utf-8-sig')).documents()[0]
        xml=xml_namespaces.serialize(objects.export(source,{},request['platform'],'CommonModule'))
        return dict(request,object_xml=self.renamed(xml),_allow_rename=True,preserve_content=True),source

    def preserved(self,content,request):
        original=metadata_context.context_objects(request['context'])[request['object_id']][0][11]
        self.assertEqual(content.streams,[])
        self.assertEqual(content.externals,[dict(name=s.val(original[i]),version=uuid.UUID(s.val(original[i+1])).bytes_le.hex()+'00000000',action=0) for i in range(1,len(original),2)])
        self.assertEqual(s.render(content.docs[2]),'{0}');self.assertEqual(s.val(content.docs[0][9]),'Renamed')

    def test_module_name_and_description_change_preserve_source_container(self):
        request,source=self.module();request.pop('source_text');content=modules.compile_change(request);expected=copy.deepcopy(source);expected[1][1][2]=s.atom('Renamed',True)
        self.assertEqual(s.render(s.Parser(content.body.decode('utf-8-sig')).documents()[0]),s.render(expected));self.preserved(content,request)

    def test_module_rename_can_also_replace_its_whole_source(self):
        from test_commonmodule_serializer import container_members
        request,_=self.module();request['preserve_content']=False
        content=modules.compile_change(request);self.assertEqual(s.val(content.docs[0][9]),'Renamed');self.assertEqual(len(content.streams),1)
        self.assertEqual(container_members(s.inflate(content.streams[0][1]))['text'].decode('utf-8-sig'),request['source_text'].replace('\n','\r\n'))

    def test_module_name_guard_remains_enabled_outside_full_export(self):
        request,_=self.module();request.pop('_allow_rename')
        with self.assertRaisesRegex(ValueError,'rename is unsupported'):modules.compile_change(request)

    def test_empty_module_rename_does_not_create_an_external_stream(self):
        request,source=self.module();docs=metadata_context.context_objects(request['context'])[request['object_id']];docs[0][11]=[s.atom(0)];docs[2]=[s.atom(0)]
        request.update(snapshot=store(docs,s.native_body_bytes([source])),context=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode(),clear_module_text=True,source_text='')
        content=modules.compile_change(request);self.preserved(content,request);self.assertEqual(s.render(content.docs[0][11]),'{0}')

    def test_form_rename_does_not_decode_or_rebuild_the_interface(self):
        request=form_cases.fixture();request.pop('module_text')
        definition='<MetaDataObject xmlns="'+xml_namespaces.MD+'" version="2.21"><Form uuid="'+request['object_id']+'"><Properties><Name>Renamed</Name><Synonym/><Comment/><FormType>Managed</FormType></Properties></Form></MetaDataObject>'
        request.update(definition_xml=definition,_allow_rename=True,preserve_content=True)
        with patch.object(forms.form_xml,'convert',side_effect=AssertionError('Interface conversion')):content=forms.compile_change(request)
        self.preserved(content,request)
        with self.assertRaisesRegex(ValueError,'rename is unsupported'):forms.compile_change(dict(request,_allow_rename=False))

    def test_common_and_owned_template_rename_preserve_content_without_decoding_target(self):
        for fixture in ('template_packets_851.json','common_template_packets_851.json'):
            with self.subTest(fixture=fixture):
                request=json.loads(Path(__file__).with_name('fixtures').joinpath(fixture).read_text(encoding='utf-8'))['change']
                request.update(definition_xml=self.renamed(request['definition_xml']),_allow_rename=True,preserve_content=True)
                for field in ('template_xml','template_data'):request.pop(field,None)
                with patch.object(templates.template_content,'convert',side_effect=AssertionError('Template conversion')):content=templates.compile_change(request)
                self.preserved(content,request)
                with self.assertRaisesRegex(ValueError,'identity or maps mismatch'):templates.compile_change(dict(request,_allow_rename=False))
