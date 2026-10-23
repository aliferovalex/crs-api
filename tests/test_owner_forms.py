"""Shared whole-form conversion matches independently compiled owner forms."""
import json
import base64
import hashlib
import uuid
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('managed_form_operations.py')).parent))
import metadata_context
import native_metadata as s
import managed_form_operations as forms
import managed_form_xml as xml
import managed_form_profiles as profiles
import v8unpack_backend as backend
import test_catalog_form_serializer as packets


def request(case,externals=False):
    r=packets.fixture();metadata,pos=s.read_record(base64.b64decode(r['snapshot']),12)
    docs=s.Parser(metadata.decode('utf-8-sig')).documents();m=docs[0]
    m[1]=s.atom(case['owner_id']);m[2]=s.atom(forms.identifiers.class_id(case['kind']));m[9]=s.atom(case['owner_name'],True)
    m[11]=m[12]=m[13]=[s.atom(0)];docs[2]=[s.atom(0)]
    payloads=[]
    if externals:
        m[11]=[s.atom(2)];docs[2]=[s.atom(2)]
        for suffix in ('.0','.2'):
            name=case['owner_id']+suffix;version=str(uuid.uuid4())
            m[11].extend([s.atom(name,True),s.atom(version)])
            docs[2].append([s.atom(name,True),s.atom(version),s.atom(1)])
            payloads.append((name,s.compress(('existing module '+suffix).encode())))
    metadata=s.text_bytes(docs);body=s.compress(case['empty_owner_body'].encode('utf-8'))
    manifest=[s.atom(0),s.atom(1),m[1],s.atom(hashlib.sha1(metadata).hexdigest(),True),s.atom(hashlib.sha1(body).hexdigest(),True),s.atom(len(payloads))]
    for name,payload in payloads:manifest.extend([s.atom(name,True),s.atom(hashlib.sha1(payload).hexdigest(),True)])
    r.update(object_id=case['owner_id'],form_kind=case['kind'],name=case['form_name'],definition_xml=case['definition_xml'],form_xml=case['form_xml'],snapshot=base64.b64encode(s.storage([metadata,body]+[payload for _,payload in payloads],s.text_bytes([manifest]))).decode(),context=base64.b64encode(s.storage([metadata],s.text_bytes([[s.atom(0)]]))).decode())
    return r


class OwnerFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=json.loads(Path(__file__).with_name('fixtures').joinpath('owner_forms_851.json').read_text(encoding='utf-8'))['cases']

    def test_whole_definition_and_interface_match_native_compilation(self):
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                owner=s.Parser(case['owner_body']).documents()[0]
                fid,body,external=forms.create_native(case['kind'],case['form_name'],'8.5.1.1529',owner,case['definition_xml'],case['form_xml'])
                self.assertEqual(fid,case['form_id'])
                self.assertEqual(backend.signature(s.Parser(body.decode('utf-8-sig')).documents()),backend.signature(s.Parser(case['body']).documents()))
                self.assertEqual(backend.signature(xml.interface(external)),backend.signature(xml.interface(case['external'].encode('utf-8'))))
                self.assertEqual(profiles.owner_name(owner,case['kind']),case['owner_name'])

    def test_main_attribute_cannot_reference_another_owner(self):
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                owner=s.Parser(case['owner_body']).documents()[0]
                broken=case['form_xml'].replace('Object.'+case['owner_name'],'Object.Unknown')
                with self.assertRaisesRegex(ValueError,'does not match its owner'):
                    forms.create_native(case['kind'],case['form_name'],'8.5.1.1529',owner,case['definition_xml'],broken)

    def test_creation_packet_matches_native_form_and_owner_collection(self):
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                result=forms.create(request(case))
                _,metadata,body,external,owner,owner_body=packets.records(result)
                self.assertEqual(result['object_id'],case['form_id'])
                self.assertEqual(s.val(metadata[0][2]),forms.identifiers.class_id(case['kind']+'Form'))
                self.assertEqual(s.val(metadata[0][3]),case['owner_id'])
                self.assertEqual(backend.signature(s.Parser(body.decode('utf-8-sig')).documents()),backend.signature(s.Parser(case['body']).documents()))
                self.assertEqual(backend.signature(xml.interface(external)),backend.signature(xml.interface(case['external'].encode('utf-8'))))
                self.assertEqual(backend.signature(s.Parser(owner_body.decode('utf-8-sig')).documents()),backend.signature(s.Parser(case['owner_body']).documents()))
                self.assertEqual(s.val(owner[0][12][1][2]),case['form_id'])

    def test_processor_description_events_and_module_match_native_change(self):
        case=next(case for case in self.cases if case['kind']=='DataProcessor');changed=case['changed']
        owner=s.Parser(case['owner_body']).documents()[0]
        _,body,external=forms.create_native('DataProcessor',case['form_name'],'8.5.1.1529',owner,changed['definition_xml'],changed['form_xml'],changed['module_text'])
        self.assertEqual(backend.signature(s.Parser(body.decode('utf-8-sig')).documents()),backend.signature(s.Parser(changed['body']).documents()))
        self.assertEqual(backend.signature(xml.interface(external)),backend.signature(xml.interface(changed['external'].encode('utf-8'))))

    def test_creation_preserves_owner_module_versions_without_copying_payloads(self):
        for case in self.cases:
            with self.subTest(kind=case['kind']):
                r=request(case,externals=True);before=metadata_context.context_metadata(base64.b64decode(r['context']),case['owner_id'])
                result=forms.create(r);graph,_,_,_,owner,_=packets.records(result)
                rows={row['name']:row for row in result['externals'] if row['object_id']==case['owner_id']}
                self.assertEqual(len(rows),2)
                for index in (2,4):
                    original=uuid.UUID(s.val(before[0][11][index])).bytes_le+bytes(4)
                    self.assertEqual(base64.b64decode(s.val(owner[0][11][index])),original)
                    row=rows[s.val(before[0][11][index-1])]
                    self.assertEqual((row['version'],row['action']),(original.hex(),0))
                self.assertEqual(s.render(owner[2]),'{0}')
                self.assertEqual(s.render(s.Parser(graph.decode('utf-8-sig')).documents()[0][7][4]),s.render(owner[0][11]))

    def test_report_events_use_current_configuration_uuid(self):
        case=next(case for case in self.cases if case['kind']=='Report');changed=case['changed']
        owner=s.Parser(case['owner_body']).documents()[0]
        with self.assertRaisesRegex(ValueError,'Configuration UUID'):
            forms.create_native('Report',case['form_name'],'8.5.1.1529',owner,changed['definition_xml'],changed['form_xml'],changed['module_text'])
        _,body,external=forms.create_native('Report',case['form_name'],'8.5.1.1529',owner,changed['definition_xml'],changed['form_xml'],changed['module_text'],configuration_id=case['configuration_id'])
        self.assertEqual(backend.signature(xml.interface(external)),backend.signature(xml.interface(changed['external'].encode('utf-8'))))

    def test_unverified_report_interface_properties_are_rejected(self):
        case=next(case for case in self.cases if case['kind']=='Report');owner=s.Parser(case['owner_body']).documents()[0]
        broken=case['form_xml'].replace('<ReportFormType>Main</ReportFormType>','<ReportFormType>Settings</ReportFormType>')
        with self.assertRaisesRegex(ValueError,'form property'):
            forms.create_native('Report',case['form_name'],'8.5.1.1529',owner,case['definition_xml'],broken)


if __name__=='__main__':unittest.main()
