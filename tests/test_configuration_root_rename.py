"""Root-name patches preserve feature UUIDs, opaque tails and other objects."""
import base64,copy,json,unittest,uuid
from pathlib import Path
from xml.etree import ElementTree as E
import test_configuration_serializer as source
import test_configuration_export as exports
from test_managed_form_creation import store
import configuration_xml as x,configuration_commit as commit,configuration_batch as batch
import metadata_context,native_metadata as s,xml_namespaces


class ConfigurationRootRenameTests(unittest.TestCase):
    def test_native_loaded_root_body_matches_exact_name_patch(self):
        case=json.loads(Path(__file__).with_name('fixtures').joinpath('configuration_root_rename_851.json').read_text(encoding='utf-8'))
        docs=s.Parser(case['source']).documents();common=x.common_properties(docs,case['id'],case['platform'])
        patches=x.xml_property_patches(case['before_xml'],case['xml'],case['id'],common,docs,case['platform'],allow_rename=True)
        self.assertEqual(patches,[(common[2].start,common[2].end,s.render(s.atom(case['name'],True)))])
        text=case['source']
        for start,end,value in reversed(patches):text=text[:start]+value+text[end:]
        self.assertEqual(text,case['body'])

    def fixture(self):
        request,raw=source.property_fixture('8.5.1.1529');docs=s.Parser(raw.decode('utf-8-sig')).documents();common=x.common_properties(docs,request['object_id'],request['platform'])
        root=E.fromstring(request['before_xml']);root[0].find('{*}Properties/{*}Name').text='RenamedRoot'
        return request,raw,docs,common,xml_namespaces.serialize(root)

    def test_explicit_root_name_patch_preserves_every_other_native_byte(self):
        request,raw,docs,common,target=self.fixture()
        patches=x.xml_property_patches(request['before_xml'],target,request['object_id'],common,docs,request['platform'],allow_rename=True)
        self.assertEqual(patches,[(common[2].start,common[2].end,'"RenamedRoot"')])
        text=raw.decode('utf-8-sig');start,end,value=patches[0];changed=s.Parser(text[:start]+value+text[end:]).documents()
        self.assertEqual(s.val(x.common_properties(changed,request['object_id'],request['platform'])[2]),'RenamedRoot')
        self.assertEqual(x.contained_objects(docs,request['object_id'],request['platform']),x.contained_objects(changed,request['object_id'],request['platform']))

    def test_single_object_name_guard_and_invalid_names_remain_rejected(self):
        request,_,docs,common,target=self.fixture()
        with self.assertRaisesRegex(ValueError,'Name changes are unsupported'):
            x.xml_property_patches(request['before_xml'],target,request['object_id'],common,docs,request['platform'])
        for name in ('','bad name','9Root','x'*81):
            root=E.fromstring(target);root[0].find('{*}Properties/{*}Name').text=name
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'Invalid metadata Name'):
                x.xml_property_patches(request['before_xml'],xml_namespaces.serialize(root),request['object_id'],common,docs,request['platform'],allow_rename=True)

    def test_rename_does_not_authorize_other_xml_changes(self):
        request,_,docs,common,target=self.fixture();root=E.fromstring(target)
        E.SubElement(root[0].find('{*}Properties'),'Unsupported').text='value'
        with self.assertRaisesRegex(ValueError,'outside supported'):
            x.xml_property_patches(request['before_xml'],xml_namespaces.serialize(root),request['object_id'],common,docs,request['platform'],allow_rename=True)

    def test_complete_export_updates_only_root_body_descriptor_and_graph(self):
        fixture=exports.ConfigurationExportTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        objects=metadata_context.context_objects(fixture.context);oid=next(key for key,docs in objects.items() if s.val(docs[0][3])==s.ZERO)
        raw=fixture.fixture['root_before'].encode('utf-8-sig');native=s.Parser(raw.decode('utf-8-sig')).documents();common=x.common_properties(native,oid,'8.5.1.1529')
        q='{'+xml_namespaces.MD+'}'
        for folder in (fixture.old,fixture.new):
            file=folder/'Configuration.xml';root=E.parse(file);root.getroot()[0].find(q+'Properties/'+q+'Comment').text=s.val(common[4]);root.write(file,encoding='utf-8')
        file=fixture.new/'Configuration.xml';root=E.parse(file);root.getroot()[0].find(q+'Properties/'+q+'Name').text='RenamedRoot';root.write(file,encoding='utf-8')
        request=dict(directory=str(fixture.new),baseline_directory=str(fixture.old),context=fixture.context,platform='8.5.1.1529',repository='Synthetic',repository_version=fixture.fixture['request']['repository_version'])
        plan,_=commit.prepare(request);self.assertEqual(plan['snapshot_ids'],[oid]);self.assertEqual(plan['new_ids'],[]);self.assertEqual(plan['removed_ids'],[])
        request.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'],snapshots={oid:store(objects[oid],raw)},originals={oid:uuid.UUID(s.val(objects[oid][0][7])).bytes_le.hex()+'00000000'})
        result=commit.serialize(request);graph,records=batch.read_packet(result['data']);self.assertEqual(len(records),1);self.assertEqual(result['changed_ids'],[oid])
        self.assertEqual(result['descriptions'][0]['name'],'RenamedRoot');self.assertEqual(s.val(s.Parser(records[0].metadata.decode('utf-8-sig')).documents()[0][9]),'RenamedRoot')
        expected=copy.deepcopy(native);x.common_properties(expected,oid,'8.5.1.1529')[2]=s.atom('RenamedRoot',True)
        self.assertEqual(s.render(s.Parser(s.inflate(records[0].body).decode('utf-8-sig')).documents()),s.render(expected))
        self.assertIn('RenamedRoot',s.render(graph))
