"""A complete real WebService with scoped QNames and selected XDTO packages."""
import base64,copy,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import metadata_object_xml as metadata
import metadata_targets as targets
import metadata_identifiers as ids
import native_metadata as s
import xml_namespaces
import configuration_commit as commit
import configuration_batch as batch
import object_change_serializer as change
import object_creation_serializer as creation
import metadata_context
import inline_object_xml
import test_object_xml_profiles as objects
import test_object_change_serializer as changes
from test_managed_form_creation import store


class WebDemoTypeTests(unittest.TestCase):
    def case(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('web_demo_types_851.json').read_text(encoding='utf-8'))

    def index(self,case):
        name=E.fromstring(case['package_xml'])[0].findtext(metadata.Q+'Properties/'+metadata.Q+'Name')
        return targets.Index([targets.Target(case['package_id'],ids.class_id('XDTOPackage'),s.ZERO,s.ZERO,name)])

    def package(self,template,parent,case):
        docs=copy.deepcopy(template);m=docs[0];name=self.index(case).targets[0].name
        m[1]=s.atom(case['package_id']);m[2]=s.atom(ids.class_id('XDTOPackage'));m[3]=s.atom(parent);m[9]=s.atom(name,True)
        for slot in (11,12,13):m[slot]=[s.atom(0)]
        m[14]=[s.atom(1),s.atom(parent),s.atom(1)];docs[2]=[s.atom(0)]
        return docs

    def test_complete_real_service_body_and_xml_export_match_native_compilation(self):
        case=self.case();index=self.index(case);_,_,raw,features=metadata.create(case['xml'],'8.5.1.1529','WebService',objects=index)
        self.assertEqual(raw.decode('utf-8-sig'),case['body']);body=s.Parser(case['body']).documents()[0];self.assertEqual(s.val(body[3][1]),'6');self.assertGreater(len(features),6)
        top=metadata.export(body,{},'8.5.1.1529','WebService',objects=index)
        self.assertEqual(metadata.create(E.tostring(top,encoding='unicode'),'8.5.1.1529','WebService',objects=index)[2],raw)
        self.assertEqual(metadata.change(case['xml'],'8.5.1.1529','WebService',body,reference_objects=index)[0],raw)

    def test_scoped_reused_prefix_survives_complete_export_rewriting(self):
        case=self.case();top,scopes=xml_namespaces.parse(case['xml']);oid=top[0].get('uuid');uris=set()
        for node in top.iter():
            if node.tag not in (metadata.Q+'XDTOValueType',metadata.Q+'XDTOReturningValueType'):continue
            prefix,name=node.text.split(':');uri=xml_namespaces.context(scopes,node)[prefix];uris.add(uri);node.text='local:'+name;node.set('xmlns:local',uri)
        rewritten=xml_namespaces.render(top,case['xml'],scopes);converted=commit.without_new_children(rewritten,oid,{},set())
        self.assertEqual(metadata.create(converted,'8.5.1.1529','WebService',objects=self.index(case))[2].decode('utf-8-sig'),case['body'])
        self.assertGreater(len(uris),1)

    def test_package_reference_is_required_and_value_list_decoration_is_rejected(self):
        case=self.case()
        with self.assertRaisesRegex(ValueError,'metadata ValueList reference'):metadata.create(case['xml'],'8.5.1.1529','WebService')
        top,scopes=xml_namespaces.parse(case['xml']);node=top.find('.//{'+xml_namespaces.READABLE+'}Presentation');node.text='caption'
        with self.assertRaisesRegex(ValueError,'presentation or check state'):metadata.create(xml_namespaces.render(top,case['xml'],scopes),'8.5.1.1529','WebService',objects=self.index(case))

    def test_default_namespace_qnames_survive_complete_export_rewriting(self):
        case=self.case();top,scopes=xml_namespaces.parse(case['xml'])
        for node in top.iter():
            if node.tag not in (metadata.Q+'XDTOValueType',metadata.Q+'XDTOReturningValueType'):continue
            prefix,name=node.text.split(':');node.text=name;node.set('xmlns',xml_namespaces.context(scopes,node)[prefix])
        text=xml_namespaces.render(top,case['xml'],scopes);converted=commit.without_new_children(text,top[0].get('uuid'),{},set())
        self.assertEqual(metadata.create(converted,'8.5.1.1529','WebService',objects=self.index(case))[2].decode('utf-8-sig'),case['body'])

    def test_complete_namespace_list_change_does_not_preserve_removed_strings(self):
        case=self.case();top,scopes=xml_namespaces.parse(case['xml']);packages=top[0].find(metadata.Q+'Properties/'+metadata.Q+'XDTOPackages');packages.remove(packages[-1]);body=s.Parser(case['body']).documents()[0]
        raw,_=metadata.change(xml_namespaces.render(top,case['xml'],scopes),'8.5.1.1529','WebService',body,reference_objects=self.index(case))
        self.assertEqual(s.val(s.Parser(raw.decode('utf-8-sig')).documents()[0][1][5][0]),'3')

    def test_removed_package_reference_removes_only_its_repository_dependency(self):
        case=self.case();seed,docs,_=changes.fixture('WebService');body=s.Parser(case['body']).documents()[0];oid=s.val(body[1][2][1][2]);parent=s.val(docs[0][3]);package=self.package(docs,parent,case)
        docs[0][1]=s.atom(oid);docs[0][9]=s.atom('MAExchange',True);features=inline_object_xml.features(body,metadata.profiles.layout('WebService'));docs[0][13]=[s.atom(len(features))]+[s.atom(value) for value in features]
        docs[0][14]=[s.atom(2),s.atom(parent),s.atom(case['package_id']),s.atom(1),s.atom(0)]
        top,scopes=xml_namespaces.parse(case['xml']);packages=top[0].find(metadata.Q+'Properties/'+metadata.Q+'XDTOPackages');packages.remove(packages[0])
        seed.update(object_id=oid,snapshot=store(docs,s.native_body_bytes([body])),context=base64.b64encode(s.storage([s.text_bytes(docs),s.text_bytes(package)],s.text_bytes([[s.atom(0)]]))).decode(),object_xml=xml_namespaces.render(top,case['xml'],scopes))
        _,updated,_,_,_=changes.unpack(change.serialize(seed));self.assertNotIn(case['package_id'],s.metadata_relations(updated[0][14]));self.assertEqual(s.metadata_relations(updated[0][14])[parent],1)

    def test_creation_records_selected_package_as_a_repository_dependency(self):
        case=self.case();request=objects.request('WebService');root=request['object_id'];context=metadata_context.context_objects(request['context']);package=self.package(context[root],root,case);context[case['package_id']]=package
        cls=ids.class_id('XDTOPackage');m=context[root][0];m[12].append([s.atom(cls),s.atom(1),s.atom(case['package_id'])]);m[12][0]=s.atom(len(m[12])-1)
        relations=s.metadata_relations(m[14]);relations[case['package_id']]=1;m[14]=[s.atom(len(relations))]+[s.atom(key) for key in relations]+[s.atom(flag) for flag in relations.values()]
        snapshot=base64.b64decode(request['snapshots'][root]);_,pos=s.read_record(snapshot,12);body,_=s.read_record(snapshot,pos);native=s.Parser(s.inflate(body).decode('utf-8-sig')).documents()[0];native.append([s.atom(cls),s.atom(1),s.atom(case['package_id'])])
        request['snapshots'][root]=store(context[root],s.native_body_bytes([native]));request['snapshots'][case['package_id']]=store(package,metadata.create(case['package_xml'],request['platform'],'XDTOPackage')[2]);request['context']=base64.b64encode(s.storage([s.text_bytes(docs) for docs in context.values()],s.text_bytes([[s.atom(0)]]))).decode();request['object_xml']=case['xml']
        result=creation.serialize(request);_,records=batch.read_packet(result['data']);record=next(row for row in records if row.object_id==result['object_id']);docs=s.Parser(record.metadata.decode('utf-8-sig')).documents()
        self.assertEqual(s.metadata_relations(docs[0][14])[case['package_id']],0);self.assertEqual(s.metadata_relations(docs[0][14])[root],1)


if __name__=='__main__':unittest.main()
