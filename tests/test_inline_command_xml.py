"""Command bodies and module ownership stay part of their parent object."""
import copy,json,unittest,uuid
from pathlib import Path
from xml.etree import ElementTree as E
import metadata_serializer as s
import inline_command_xml as commands
import flat_object_serializer as flat
import object_change_serializer as change
import test_document_serializer as document
import test_object_change_serializer as snapshots
import constant_serializer as creation

Q=commands.Q;CID='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


def xml():
    root=E.fromstring(document.xml());node=E.SubElement(root[0].find(Q+'ChildObjects'),Q+'Command',uuid=CID);props=E.SubElement(node,Q+'Properties')
    E.SubElement(props,Q+'Name').text='TestCommand';E.SubElement(props,Q+'Comment').text='Original'
    E.SubElement(props,Q+'Group').text='NavigationPanelOrdinary'
    return E.tostring(root,encoding='unicode')


class InlineCommandTests(unittest.TestCase):
    def test_new_document_with_command_module_uses_shared_creation_packet(self):
        request=document.fixture();request['document_xml']=xml();request['inline_modules']=[dict(object_id=CID,source_text='// new command')]
        result=creation.serialize(request);self.assertEqual(result['inline_streams'],[dict(object_id=result['object_id'],name=CID+'.2')])
        self.assertEqual(next(item['action'] for item in result['externals'] if item['name']==CID+'.2'),1)
        import base64
        raw=s.inflate(base64.b64decode(result['data'])[18:]);_,pos=s.read_record(raw,0);storage,_=s.read_record(raw,pos+4);meta,pos=s.read_record(storage,12);_,pos=s.read_record(storage,pos);module,_=s.read_record(storage,pos)
        self.assertIn(b'// new command',s.inflate(module));docs=s.Parser(meta.decode('utf-8-sig')).documents();self.assertEqual(s.val(docs[0][13][1]),CID)

    def test_creation_rejects_duplicate_or_foreign_inline_module_owner(self):
        for modules in ([dict(object_id=CID,source_text='one'),dict(object_id=CID,source_text='two')],[dict(object_id=str(uuid.uuid4()),source_text='foreign')]):
            request=document.fixture();request['document_xml']=xml();request['inline_modules']=modules
            with self.subTest(modules=modules),self.assertRaises(ValueError):creation.serialize(request)

    def test_parent_edit_adds_command_and_its_owned_module(self):
        request,_,_=snapshots.fixture('Document',document.xml());request['object_xml']=xml();request['inline_modules']=[dict(object_id=CID,source_text='// whole command module')]
        result=change.serialize(request);call,docs,raw,storage,pos=snapshots.unpack(result);data,_=s.read_record(storage,pos)
        self.assertEqual(result['external_owners'],[CID]);self.assertEqual(s.val(docs[0][13][1]),CID)
        self.assertEqual(s.val(docs[0][11][1]),CID+'.2');self.assertIn(b'// whole command module',s.inflate(data))
        self.assertIn('TestCommand',raw.decode('utf-8-sig'));self.assertEqual(len(call.findall('.//{'+s.NS+'}externals/{'+s.NS+'}value')),1)

    def test_whole_metadata_edit_can_preserve_existing_command_stream(self):
        request,docs,raw=snapshots.fixture('Document',xml())
        version=str(uuid.uuid4());docs[0][11]=[s.atom(1),s.atom(CID+'.2',True),s.atom(version)];docs[2]=[s.atom(1),[s.atom(CID+'.2',True),s.atom(version),s.atom(1)]]
        # A getObjects snapshot does not contain the external bytes.
        saved=copy.deepcopy(docs);saved[2]=[s.atom(0)]
        from test_managed_form_serializer import store
        import base64
        request['snapshot']=store(saved,raw);request['context']=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode();request['object_xml']=request['object_xml'].replace('Original','Changed')
        call,new,_,_,_=snapshots.unpack(change.serialize(request))
        self.assertEqual(s.val(new[2][0]),'0');self.assertEqual(call.find('.//{'+s.NS+'}externals/{'+s.NS+'}value/{'+s.NS+'}second/{'+s.NS+'}action').get('value'),'0')

    def test_unknown_properties_and_foreign_modules_rejected(self):
        for mutation in ('property','foreign','duplicate'):
            request,_,_=snapshots.fixture('Document',document.xml());root=E.fromstring(xml())
            if mutation=='property':E.SubElement(root.find('.//'+Q+'Command/'+Q+'Properties'),Q+'ModifiesData').text='true'
            elif mutation=='foreign':request['inline_modules']={'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb':'// foreign'}
            else:
                node=root.find('.//'+Q+'Command');root[0].find(Q+'ChildObjects').append(copy.deepcopy(node))
            request['object_xml']=E.tostring(root,encoding='unicode')
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):change.serialize(request)


if __name__=='__main__':unittest.main()
