"""Whole native module files share creation/change packet assembly."""
import base64,copy,json,sys,unittest,uuid
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import object_xml_profiles as profiles
import object_creation_serializer as creation
import object_change_serializer as change
import configuration_batch as batch
import native_metadata as s
import metadata_context
import metadata_identifiers as ids
import metadata_object_xml as metadata
import test_object_change_serializer as changes
import test_object_xml_profiles as cases
import test_object_creation_serializer as constants
from test_commonmodule_serializer import container_members
from test_managed_form_creation import store


class OwnerModuleTests(unittest.TestCase):
    def test_explicit_removal_drops_a_module_without_replacing_other_streams(self):
        request,docs,raw=changes.fixture('DataProcessor',externals=True);oid=request['object_id'];version=s.val(docs[0][11][4]);request['removed_modules']=['ObjectModule']
        _,updated,body,_,_=changes.unpack(change.serialize(request))
        self.assertEqual(body,raw);self.assertEqual([s.val(name) for name in updated[0][11][1::2]],[oid+'.2'])
        self.assertEqual(base64.b64decode(s.val(updated[0][11][2]))[:16],uuid.UUID(version).bytes_le);self.assertEqual(s.render(updated[2]),'{0}')

    def test_removal_rejects_unknown_duplicate_and_conflicting_module_inputs(self):
        request,_,_=changes.fixture('DataProcessor',externals=True)
        for options in ({'removed_modules':['Unknown']},{'removed_modules':['ObjectModule','ObjectModule']},{'removed_modules':'ObjectModule'},{'removed_modules':['ObjectModule'],'modules':{'ObjectModule':'conflict'}},{'removed_inline_modules':['aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa']},{'removed_inline_modules':[[]]}):
            with self.subTest(options=options),self.assertRaisesRegex(ValueError,'Invalid module removals'):change.serialize(dict(request,**options))

    def cases(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('owner_modules_851.json').read_text(encoding='utf-8'))['cases']

    def journal(self):
        request=cases.request('DocumentJournal');objects=metadata_context.context_objects(request['context']);parent=request['object_id'];root=objects[parent];doc=copy.deepcopy(root);did='dddddddd-dddd-4ddd-8ddd-dddddddddddd';m=doc[0]
        m[1]=s.atom(did);m[2]=s.atom(ids.class_id('Document'));m[3]=s.atom(parent);m[9]=s.atom('Referenced',True);m[10]=s.atom(0);m[11]=[s.atom(0)];m[12]=[s.atom(0)];m[13]=[s.atom(0)];m[14]=[s.atom(1),s.atom(parent),s.atom(1)]
        top=E.fromstring(cases.xml('Document'));top[0].set('uuid',did);top[0].find(metadata.Q+'Properties/'+metadata.Q+'Name').text='Referenced';docbody=metadata.create(E.tostring(top,encoding='unicode'),request['platform'],'Document')[2]
        snapshot=base64.b64decode(request['snapshots'][parent]);_,pos=s.read_record(snapshot,12);raw,_=s.read_record(snapshot,pos);body=s.Parser(s.inflate(raw).decode('utf-8-sig')).documents()[0]
        row=next((r for r in body if isinstance(r,list) and r and isinstance(r[0],s.Atom) and s.val(r[0])==ids.class_id('Document')),None)
        if row is None:body.append([s.atom(ids.class_id('Document')),s.atom(1),s.atom(did)])
        else:row[:]=[row[0],s.atom(1),s.atom(did)]
        root[0][12].append([s.atom(ids.class_id('Document')),s.atom(1),s.atom(did)]);root[0][12][0]=s.atom(len(root[0][12])-1)
        relations=s.metadata_relations(root[0][14]);relations[did]=1;root[0][14]=[s.atom(len(relations))]+[s.atom(key) for key in relations]+[s.atom(flag) for flag in relations.values()];objects[did]=doc
        request['context']=base64.b64encode(s.storage([s.text_bytes(d) for d in objects.values()],s.text_bytes([[s.atom(0)]]))).decode();request['snapshots'][parent]=store(root,s.native_body_bytes([body]));request['snapshots'][did]=store(doc,docbody)
        top=E.fromstring(request['object_xml']);refs=E.SubElement(top[0].find(metadata.Q+'Properties'),metadata.Q+'RegisteredDocuments');E.SubElement(refs,'{http://v8.1c.ru/8.3/xcf/readable}Item').text='Document.Referenced';request['object_xml']=E.tostring(top,encoding='unicode')
        return request,doc

    def test_creation_uses_independently_verified_suffixes_and_complete_texts(self):
        for case in self.cases():
            with self.subTest(kind=case['kind']):
                request=self.journal()[0] if case['kind']=='DocumentJournal' else constants.fixture('8.5.1.1529') if case['kind']=='Constant' else cases.request(case['kind']);request['modules']=case['sources']
                result=creation.serialize(request);_,records=batch.read_packet(result['data']);record=next(row for row in records if row.object_id==result['object_id']);self.assertEqual(profiles.module_files(case['kind']),case['modules'])
                self.assertEqual(set(dict(record.externals)),{record.object_id+suffix for suffix in case['modules'].values()})
                for name,suffix in case['modules'].items():
                    text=container_members(s.inflate(dict(record.externals)[record.object_id+suffix]))['text'].decode('utf-8-sig').replace('\r\n','\n')
                    self.assertEqual(text,case['sources'][name])

    def test_change_preserves_body_and_unrelated_stream_versions(self):
        for case in self.cases():
            with self.subTest(kind=case['kind']):
                if case['kind']=='DocumentJournal':
                    source,doc=self.journal();request,docs,_=changes.fixture('DataProcessor');request['object_type']='DocumentJournal';request['object_xml']=source['object_xml'];docs[0][2]=s.atom(ids.class_id('DocumentJournal'))
                    doc[0][3]=docs[0][3];doc[0][14]=[s.atom(1),docs[0][3],s.atom(1)];docs[0][14]=[s.atom(2),docs[0][3],doc[0][1],s.atom(1),s.atom(0)]
                    raw=metadata.create(source['object_xml'],request['platform'],'DocumentJournal',objects={s.val(doc[0][1]):doc})[2]
                else:
                    xml=constants.xml() if case['kind']=='Constant' else cases.xml(case['kind']);request,docs,raw=changes.fixture(case['kind'],xml);doc=None
                oid=request['object_id'];other=oid+'.7f';version=str(uuid.uuid4())
                docs[0][11]=[s.atom(1),s.atom(other,True),s.atom(version)];docs[2]=[s.atom(0)];request['snapshot']=store(docs,raw);request['context']=base64.b64encode(s.storage([s.text_bytes(d) for d in ([docs,doc] if doc else [docs])],s.text_bytes([[s.atom(0)]]))).decode();request['modules']=case['sources']
                call,updated,body,storage,pos=changes.unpack(change.serialize(request));self.assertEqual(body,raw)
                refs=updated[0][11];names={s.val(refs[i]):base64.b64decode(s.val(refs[i+1])) for i in range(1,len(refs),2)}
                self.assertEqual(names[other][:16],uuid.UUID(version).bytes_le);self.assertEqual(set(names),{other}|{oid+suffix for suffix in case['modules'].values()})
                for name in case['sources']:
                    payload,pos=s.read_record(storage,pos);text=container_members(s.inflate(payload))['text'].decode('utf-8-sig').replace('\r\n','\n');self.assertEqual(text,case['sources'][name])


if __name__=='__main__':unittest.main()
