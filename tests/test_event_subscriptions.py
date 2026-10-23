"""Native subscription bodies, group features and object-type categories."""
import base64
import copy
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree as E
import test_defined_types
from test_managed_form_creation import store
import metadata_object_xml as objects
import metadata_context
import metadata_type_references as references
import metadata_type_sets as sets
import native_references
import native_metadata as s


class EventSubscriptionTests(unittest.TestCase):
    def fixture(self):
        return json.loads(Path(__file__).with_name('fixtures').joinpath('event_subscriptions_851.json').read_text(encoding='utf-8'))

    def request(self):
        data=self.fixture();rows=data['samples']+[data['root']];docs=[s.Parser(row['metadata']).documents() for row in rows]
        return dict(platform='8.5.1.1529',context=base64.b64encode(s.storage([s.text_bytes(d) for d in docs],s.text_bytes([[s.atom(0)]]))).decode(),reference_snapshots={s.val(d[0][1]):store(d,row['body'].encode('utf-8-sig')) for d,row in zip(docs,rows)})

    def test_all_native_sources_events_and_handlers_roundtrip(self):
        request=self.request();reader=native_references.Catalog(request)
        for case in self.fixture()['samples'][2:]:
            with self.subTest(name=case['name']):
                resolved=references.resolve(case['xml'],request)
                body=objects.create(case['xml'],request['platform'],'EventSubscription',objects=reader.targets,type_references=resolved)[2]
                self.assertEqual(s.render(s.Parser(body.decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))
                native=s.metadata_relations(s.Parser(case['metadata']).documents()[0][14]);parent=s.val(s.Parser(case['metadata']).documents()[0][3])
                self.assertEqual(references.object_ids(case['xml'],reader),set(native)-{parent})
                exported=objects.export(s.Parser(case['body']).documents()[0],{},request['platform'],'EventSubscription',objects=reader.targets,type_references=resolved)
                self.assertEqual(objects.create(E.tostring(exported,encoding='unicode'),request['platform'],'EventSubscription',objects=reader.targets,type_references=resolved)[2],body)

    def test_object_category_is_distinct_from_reference_and_groups(self):
        request=self.request();catalog=self.fixture()['samples'][1];reader=native_references.Catalog(request)
        self.assertEqual(references.reference_definition('cfg:CatalogObject.ProbeCatalog'),('Catalog','ProbeCatalog','Object'))
        self.assertNotEqual(reader.type_id('Catalog','ProbeCatalog','Object'),reader.type_id('Catalog','ProbeCatalog','Ref'))
        self.assertNotEqual(reader.type_id('Catalog','ProbeCatalog','Object'),sets.profile()['cfg:CatalogObject'])
        self.assertNotEqual(reader.type_id('Catalog','ProbeCatalog','Object'),catalog['id'])

    def test_group_dependency_follows_current_root_feature_uuid(self):
        request=self.request();case=next(row for row in self.fixture()['samples'] if row['name']=='ProbeCatalogObject');reader=native_references.Catalog(request)
        before=references.object_ids(case['xml'],reader);self.assertEqual(len(before),1);old=next(iter(before));new='77777777-7777-4777-8777-777777777777'
        data=self.fixture();rootdocs=s.Parser(data['root']['metadata']).documents();oid=s.val(rootdocs[0][1]);body=data['root']['body'].replace(old,new)
        rootdocs[0][13]=[s.atom(new) if s.val(v)==old else v for v in rootdocs[0][13]]
        context=metadata_context.context_objects(request['context']);context[oid]=rootdocs
        request['context']=base64.b64encode(s.storage([s.text_bytes(d) for d in context.values()],s.text_bytes([[s.atom(0)]]))).decode();request['reference_snapshots'][oid]=store(rootdocs,body.encode('utf-8-sig'))
        self.assertEqual(references.object_ids(case['xml'],native_references.Catalog(request)),{new})
        self.assertEqual(references.resolve(case['xml'],request),{'cfg:CatalogObject':sets.profile()['cfg:CatalogObject']})

    def test_group_dependency_requires_verified_root_snapshot_and_feature_map(self):
        request=self.request();case=next(row for row in self.fixture()['samples'] if row['name']=='ProbeCatalogObject');rootdocs=s.Parser(self.fixture()['root']['metadata']).documents();oid=s.val(rootdocs[0][1])
        request['reference_snapshots'].pop(oid)
        with self.assertRaisesRegex(ValueError,'snapshot is required'):references.object_ids(case['xml'],native_references.Catalog(request))
        request=self.request();rootdocs[0][13]=[s.atom(0)];context=metadata_context.context_objects(request['context']);context[oid]=rootdocs
        request['context']=base64.b64encode(s.storage([s.text_bytes(d) for d in context.values()],s.text_bytes([[s.atom(0)]]))).decode();request['reference_snapshots'][oid]=store(rootdocs,self.fixture()['root']['body'].encode('utf-8-sig'))
        with self.assertRaisesRegex(ValueError,'feature map differs'):references.object_ids(case['xml'],native_references.Catalog(request))

    def test_switching_group_and_specific_source_reconciles_native_dependencies(self):
        request=self.request();cases=self.fixture()['samples'];before=next(row for row in cases if row['name']=='ProbeCatalogObject');after=next(row for row in cases if row['name']=='ProbeSpecific');source=s.Parser(before['body']).documents()[0]
        root=E.fromstring(after['xml']);root[0].set('uuid',before['id']);root[0].find(objects.Q+'Properties/'+objects.Q+'Name').text=before['name'];xml=E.tostring(root,encoding='unicode');reader=native_references.Catalog(request)
        raw,_=objects.change(xml,request['platform'],'EventSubscription',source,reference_objects=reader.targets,type_references=references.resolve(xml,request))
        old=s.metadata_relations(s.Parser(before['metadata']).documents()[0][14]);new=references.reconcile(request,source,s.Parser(raw.decode('utf-8-sig')).documents()[0],objects.profiles.layout('EventSubscription'),old,before['id'],xml)
        self.assertEqual(new,s.metadata_relations(s.Parser(after['metadata']).documents()[0][14]))

    def test_unknown_groups_events_and_missing_source_reject(self):
        request=self.request();reader=native_references.Catalog(request);case=self.fixture()['samples'][2]
        for key,value in [('Event','UnknownEvent'),('Source',None)]:
            root=E.fromstring(case['xml']);props=root[0].find(objects.Q+'Properties')
            if value is None:props.remove(props.find(objects.Q+key))
            else:props.find(objects.Q+key).text=value
            with self.subTest(property=key),self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),request['platform'],'EventSubscription',objects=reader.targets)
        with self.assertRaises(ValueError):references.resolve(case['xml'].replace('cfg:CatalogObject.ProbeCatalog','cfg:UnknownObject'),request)
        with self.assertRaises(ValueError):sets.references({'cfg:CatalogObject':'77777777-7777-4777-8777-777777777777'})

    def test_subscriptions_module_and_specific_source_compile_in_one_packet(self):
        import test_final_native_references as cases
        import configuration_commit as commit
        import configuration_batch as batch
        helper=cases.FinalNativeReferenceTests();request,_,_,_,_=helper.case();self.addCleanup(helper.doCleanups)
        directory=Path(request['directory']);path=directory/'Configuration.xml';root=E.parse(path);children=root.getroot()[0].find(objects.Q+'ChildObjects')
        for case in self.fixture()['samples']:
            folder=directory/(case['kind']+'s');folder.mkdir(exist_ok=True);(folder/(case['name']+'.xml')).write_bytes(case['xml'].encode('utf-8'));E.SubElement(children,objects.Q+case['kind']).text=case['name']
            if case['kind']=='CommonModule':
                ext=folder/case['name']/'Ext';ext.mkdir(parents=True);(ext/'Module.bsl').write_bytes(b'Procedure BeforeWrite(Source, Cancel) Export\r\nEndProcedure\r\nProcedure AfterWrite(Source) Export\r\nEndProcedure\r\n')
        root.write(path,encoding='utf-8');plan,_=commit.prepare(request);request.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
        _,records=batch.read_packet(commit.serialize(request)['data']);records={row.object_id:row for row in records}
        reader=native_references.Catalog(request)
        for case in self.fixture()['samples'][2:]:
            actual=s.Parser(s.inflate(records[case['id']].body).decode('utf-8-sig')).documents()
            self.assertEqual(s.render(actual),s.render(s.Parser(case['body']).documents()))
            relations=s.metadata_relations(s.Parser(records[case['id']].metadata.decode('utf-8-sig')).documents()[0][14])
            if case['name']!='ProbeSpecific':self.assertTrue(sets.dependencies(references.required(case['xml']),reader)<=set(relations))
            else:self.assertEqual(relations[self.fixture()['samples'][1]['id']],0)
