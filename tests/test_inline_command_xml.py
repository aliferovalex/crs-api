"""Command bodies and module ownership stay part of their parent object."""
import copy, unittest, uuid
from xml.etree import ElementTree as E
import native_metadata as s
import inline_metadata_xml as inline_metadata
import inline_command_xml as commands
import object_change_serializer as change
import test_document_serializer as document
import test_object_change_serializer as snapshots
import object_creation_serializer as creation

Q=inline_metadata.Q;CID='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


def xml():
    root=E.fromstring(document.xml());node=E.SubElement(root[0].find(Q+'ChildObjects'),Q+'Command',uuid=CID);props=E.SubElement(node,Q+'Properties')
    E.SubElement(props,Q+'Name').text='TestCommand';E.SubElement(props,Q+'Comment').text='Original'
    E.SubElement(props,Q+'Group').text='NavigationPanelOrdinary'
    return E.tostring(root,encoding='unicode')


class InlineCommandTests(unittest.TestCase):
    def test_removal_drops_only_the_command_stream_and_preserves_other_versions(self):
        import base64
        from test_managed_form_creation import store
        second='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
        top=E.fromstring(xml());child=copy.deepcopy(top.find('.//'+Q+'Command'));child.set('uuid',second);child.find(Q+'Properties/'+Q+'Name').text='RetainedCommand';top[0].find(Q+'ChildObjects').append(child)
        request,docs,raw=snapshots.fixture('Document',E.tostring(top,encoding='unicode'))
        oid=request['object_id'];versions={name:str(uuid.uuid4()) for name in (CID+'.2',second+'.2',oid+'.0')}
        docs[0][11]=[s.atom(len(versions))]
        for name,version in versions.items():docs[0][11].extend((s.atom(name,True),s.atom(version)))
        docs[2]=[s.atom(0)];request['snapshot']=store(docs,raw);request['context']=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode()
        children=top[0].find(Q+'ChildObjects');children.remove(children.find(Q+'Command'));request['object_xml']=E.tostring(top,encoding='unicode')
        call,updated,body,_,_=snapshots.unpack(change.serialize(request))
        refs=updated[0][11];actual={s.val(refs[i]):base64.b64decode(s.val(refs[i+1]))[:16] for i in range(1,len(refs),2)}
        self.assertEqual(actual,{name:uuid.UUID(version).bytes_le for name,version in versions.items() if name!=CID+'.2'})
        self.assertEqual({s.val(v) for v in updated[0][13][1:]},{second});self.assertEqual(s.render(updated[2]),'{0}')
        entries=call.findall('.//{'+s.NS+'}externals/{'+s.NS+'}value')
        self.assertEqual({entry.find('{'+s.NS+'}first').get('value') for entry in entries},set(actual))
        self.assertTrue(all(entry.find('.//{'+s.NS+'}action').get('value')=='0' for entry in entries))
        self.assertNotIn(CID,body.decode('utf-8-sig'))

    def test_document_command_complete_xml_export_round_trips(self):
        import object_xml_profiles
        profile=object_xml_profiles.layout('Document')['command_collections']['Command']
        source=E.fromstring(xml()).find('.//'+Q+'Command');oid,name,entry=inline_metadata.read(source,profile)
        restored=inline_metadata.export(entry,profile)
        actual=inline_metadata.read(restored,profile);self.assertEqual(actual[:2],(oid,name));self.assertEqual(s.render(actual[2]),s.render(entry))
        self.assertEqual(restored.findtext(Q+'Properties/'+Q+'Comment'),'Original')

    def test_new_document_with_command_module_uses_shared_creation_packet(self):
        request=document.fixture();request['object_xml']=xml();request['inline_modules']=[dict(object_id=CID,source_text='// new command')]
        result=creation.serialize(request);self.assertEqual(result['inline_streams'],[dict(object_id=result['object_id'],name=CID+'.2')])
        self.assertEqual(next(item['action'] for item in result['externals'] if item['name']==CID+'.2'),1)
        import base64
        raw=s.inflate(base64.b64decode(result['data'])[18:]);_,pos=s.read_record(raw,0);storage,_=s.read_record(raw,pos+4);meta,pos=s.read_record(storage,12);_,pos=s.read_record(storage,pos);module,_=s.read_record(storage,pos)
        self.assertIn(b'// new command',s.inflate(module));docs=s.Parser(meta.decode('utf-8-sig')).documents();self.assertEqual(s.val(docs[0][13][1]),CID)

    def test_creation_rejects_duplicate_or_foreign_inline_module_owner(self):
        for modules in ([dict(object_id=CID,source_text='one'),dict(object_id=CID,source_text='two')],[dict(object_id=str(uuid.uuid4()),source_text='foreign')]):
            request=document.fixture();request['object_xml']=xml();request['inline_modules']=modules
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
        from test_managed_form_creation import store
        import base64
        request['snapshot']=store(saved,raw);request['context']=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode();request['object_xml']=request['object_xml'].replace('Original','Changed')
        call,new,_,_,_=snapshots.unpack(change.serialize(request))
        self.assertEqual(s.val(new[2][0]),'0');self.assertEqual(call.find('.//{'+s.NS+'}externals/{'+s.NS+'}value/{'+s.NS+'}second/{'+s.NS+'}action').get('value'),'0')

    def test_unknown_properties_and_foreign_modules_rejected(self):
        for mutation in ('property','foreign','duplicate'):
            request,_,_=snapshots.fixture('Document',document.xml());root=E.fromstring(xml())
            if mutation=='property':E.SubElement(root.find('.//'+Q+'Command/'+Q+'Properties'),Q+'UnknownProperty').text='true'
            elif mutation=='foreign':request['inline_modules']={'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb':'// foreign'}
            else:
                node=root.find('.//'+Q+'Command');root[0].find(Q+'ChildObjects').append(copy.deepcopy(node))
            request['object_xml']=E.tostring(root,encoding='unicode')
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):change.serialize(request)


if __name__=='__main__':unittest.main()
