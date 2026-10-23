"""New owners carry forms and complete templates in the same creation graph."""
import base64
import copy
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from xml.etree import ElementTree as E

import test_owned_form_creation as forms
import test_object_xml_profiles as fixtures
import object_creation_serializer as creation
import configuration_batch as batch
import metadata_context
import metadata_identifiers as ids
import native_collection_editor as collections
import native_metadata as s
import preparation_plan
import template_content
import template_serializer
from test_managed_form_creation import store

Q=forms.Q


def request(kind='Catalog'):
    result=fixtures.request(kind);text,entries=forms.add_forms(result['object_xml'],kind)
    result.update(object_xml=text,forms=entries,templates=[])
    root=E.fromstring(text);children=root[0].find(Q+'ChildObjects')
    witness=json.loads(Path(__file__).with_name('fixtures').joinpath('template_packets_851.json').read_text(encoding='utf-8'))['create']
    for index,typ in enumerate(template_content.PROFILES):
        name='Template'+str(index);oid=str(uuid.UUID(int=0xdddddddd000040008000000000000000+index))
        definition=E.fromstring(witness['definition_xml']);definition[0].set('uuid',oid);props=definition[0].find(Q+'Properties')
        props.find(Q+'Name').text=name;props.find(Q+'TemplateType').text=typ
        entry=dict(name=name,definition_xml=E.tostring(definition,encoding='unicode'))
        if typ=='DataCompositionSchema':entry['template_xml']=witness['template_xml']
        else:entry['template_data']=base64.b64encode(bytes(range(256)) if typ=='BinaryData' else b'\xef\xbb\xbffull text\r\n').decode()
        E.SubElement(children,Q+'Template').text=name;result['templates'].append(entry)
    if kind=='Report':
        props=root[0].find(Q+'Properties');node=props.find(Q+'MainDataCompositionSchema')
        if node is None:node=E.SubElement(props,Q+'MainDataCompositionSchema')
        node.text='Report.'+props.findtext(Q+'Name')+'.Template.Template2'
    result['object_xml']=E.tostring(root,encoding='unicode');return result


class OwnedTemplateCreationTests(unittest.TestCase):
    def test_all_mapped_new_owners_share_child_metadata_and_complete_content(self):
        for kind in ('Catalog','Document','DataProcessor','Report','InformationRegister','AccumulationRegister','ChartOfAccounts'):
            with self.subTest(kind=kind):
                r=request(kind);result=creation.serialize(r,batch_relations=True)
                _,records=batch.read_packet(result['data']);by_id={row.object_id:row for row in records};oid=result['object_id']
                owner=s.Parser(by_id[oid].metadata.decode('utf-8-sig')).documents()[0]
                self.assertEqual(len(metadata_context.children(owner)),5)
                for index,entry in enumerate(r['templates']):
                    tid,_,raw=template_serializer.native_definition(entry['definition_xml'],r['platform']);record=by_id[tid]
                    metadata=s.Parser(record.metadata.decode('utf-8-sig')).documents()[0]
                    self.assertEqual(s.val(metadata[2]),ids.class_id('Template'));self.assertEqual(s.val(metadata[3]),oid)
                    self.assertEqual(s.val(metadata[10]),str(index));self.assertIn((tid,ids.class_id('Template')),metadata_context.children(owner))
                    self.assertEqual(s.inflate(record.body),raw)
                    self.assertEqual(s.inflate(record.externals[0][1]),template_content.convert(dict(r,**entry)))
                    self.assertEqual(next(e for e in result['externals'] if e['object_id']==tid)['action'],0)

    def test_file_input_order_cannot_change_native_collection_positions(self):
        r=request();r['forms'].reverse();r['templates'].reverse();result=creation.serialize(r)
        positions={row['id']:row['pos'] for row in result['descriptions']}
        for entry in r['templates']:
            tid=E.fromstring(entry['definition_xml'])[0].get('uuid');self.assertEqual(positions[tid],int(entry['name'][-1]))
        self.assertEqual(positions[forms.FIDS[0]],0);self.assertEqual(positions[forms.FIDS[1]],1)

    def test_repeated_cross_collection_uuid_and_missing_files_reject(self):
        r=request();top=E.fromstring(r['templates'][0]['definition_xml']);top[0].set('uuid',forms.FIDS[0]);r['templates'][0]['definition_xml']=E.tostring(top,encoding='unicode')
        with self.assertRaisesRegex(ValueError,'Duplicate or mismatched'):creation.serialize(r)
        r=request();r['templates'].pop()
        with self.assertRaisesRegex(ValueError,'creation Template reference'):creation.serialize(r)

    def test_preparation_reads_templates_next_to_new_owner(self):
        r=request()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'Catalogs/NewOwner.xml';path.parent.mkdir();path.write_text(r['object_xml'],encoding='utf-8')
            for entry in r['forms']:
                file=path.with_suffix('')/'Forms'/(entry['name']+'.xml');file.parent.mkdir(parents=True,exist_ok=True);file.write_text(entry['definition_xml'],encoding='utf-8')
                ext=file.with_suffix('')/'Ext';ext.mkdir(parents=True);(ext/'Form.xml').write_text(entry['form_xml'],encoding='utf-8')
            for entry in r['templates']:
                file=path.with_suffix('')/'Templates'/(entry['name']+'.xml');file.parent.mkdir(parents=True,exist_ok=True);file.write_text(entry['definition_xml'],encoding='utf-8')
                ext=file.with_suffix('')/'Ext';ext.mkdir(parents=True);typ=template_content.kind(entry['definition_xml'])
                (ext/template_content.PROFILES[typ]['file']).write_bytes(entry['template_xml'].encode('utf-8') if typ=='DataCompositionSchema' else base64.b64decode(entry['template_data']))
            plan=preparation_plan.plan(dict(xml_path=str(path),context=r['context'],platform=r['platform']))
            self.assertEqual(plan['templates'],r['templates'])

    def test_followup_template_creation_accepts_each_mapped_owner_layout(self):
        for kind in ('Catalog','Document','DataProcessor','Report','InformationRegister','AccumulationRegister','ChartOfAccounts'):
            with self.subTest(kind=kind):
                r=request(kind);compiled=creation.serialize(r,batch_relations=True,contents_only=True)
                oid=E.fromstring(r['object_xml'])[0].get('uuid');objects={}
                for key,content in compiled.objects.items():
                    docs=copy.deepcopy(content.docs);m=docs[0];m[0]=s.atom(5);m[5]=m[6]=s.atom(1)
                    for index in (7,8):m[index]=s.atom(str(uuid.UUID(bytes_le=base64.b64decode(s.val(m[index]))[:16])))
                    for index in range(2,len(m[11]),2):m[11][index]=s.atom(str(uuid.UUID(bytes_le=base64.b64decode(s.val(m[11][index]))[:16])))
                    docs[2]=[s.atom(0)];objects[key]=docs
                definition=E.fromstring(r['templates'][0]['definition_xml']);definition[0].set('uuid','eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee')
                definition[0].find(Q+'Properties/'+Q+'Name').text='AdditionalTemplate'
                call=dict(platform=r['platform'],object_id=oid,context=base64.b64encode(s.storage([s.text_bytes(d) for d in objects.values()],s.text_bytes([[s.atom(0)]]))).decode(),
                          snapshot=store(objects[oid],compiled.objects[oid].body),original_version=uuid.UUID(s.val(objects[oid][0][7])).bytes_le.hex()+'00000000',
                          definition_xml=E.tostring(definition,encoding='unicode'),template_data=r['templates'][0]['template_data'])
                result=template_serializer.create(call);_,records=batch.read_packet(result['data'])
                metadata=s.Parser(records[0].metadata.decode('utf-8-sig')).documents()[0]
                self.assertEqual(s.val(metadata[3]),oid);self.assertEqual(s.val(metadata[10]),'3')


if __name__=='__main__':unittest.main()
