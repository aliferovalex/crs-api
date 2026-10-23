"""Whole scheduled-job XML and reusable method/integer property profiles."""
import base64
import copy
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree as E
import test_defined_types
import metadata_object_xml as objects
import metadata_targets
import metadata_identifiers as ids
import native_metadata as s


class ScheduledJobTests(unittest.TestCase):
    def samples(self):
        return json.loads(Path(__file__).with_name('fixtures').joinpath('scheduled_jobs_851.json').read_text(encoding='utf-8'))['samples']

    def targets(self):
        module=self.samples()[0]
        return metadata_targets.Index([metadata_targets.Target(module['id'],ids.class_id('CommonModule'),s.ZERO,s.ZERO,module['name'])])

    def test_native_property_variants_roundtrip(self):
        targets=self.targets()
        bounds=json.loads(Path(__file__).with_name('fixtures').joinpath('scheduled_jobs_851.json').read_text(encoding='utf-8'))['bounds']
        for case in self.samples()[1:]+bounds:
            with self.subTest(name=case['name']):
                raw=objects.create(case['xml'],'8.5.1.1529','ScheduledJob',objects=targets)[2]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))
                xml=objects.export(s.Parser(case['body']).documents()[0],{},'8.5.1.1529','ScheduledJob',objects=targets)
                self.assertEqual(objects.create(E.tostring(xml,encoding='unicode'),'8.5.1.1529','ScheduledJob',objects=targets)[2],raw)

    def test_change_rebuilds_properties_and_method_member(self):
        _,before,_,after=self.samples();source=s.Parser(before['body']).documents()[0];target=E.fromstring(after['xml'])
        target[0].set('uuid',before['id']);target[0].find(objects.Q+'Properties/'+objects.Q+'Name').text=before['name']
        raw,_=objects.change(E.tostring(target,encoding='unicode'),'8.5.1.1529','ScheduledJob',source,objects=self.targets())
        expected=s.Parser(after['body']).documents()[0];common=objects.at(expected,[1,1]);common[1][2]=s.atom(before['id']);common[2]=s.atom(before['name'],True)
        self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()[0]),s.render(expected))

    def test_invalid_method_and_integer_values_are_rejected(self):
        original=self.samples()[1]['xml']
        for value in ('CommonModule.ProbeJobs','CommonModule.Missing.Run','CommonModule.ProbeJobs.','CommonModule.ProbeJobs.12Bad'):
            root=E.fromstring(original);root[0].find(objects.Q+'Properties/'+objects.Q+'MethodName').text=value
            with self.subTest(method=value),self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','ScheduledJob',objects=self.targets())
        for value in ('-1','01','1.5','2147483648','true',''):
            root=E.fromstring(original);root[0].find(objects.Q+'Properties/'+objects.Q+'RestartCountOnFailure').text=value
            with self.subTest(integer=value),self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','ScheduledJob',objects=self.targets())

    def test_job_and_new_module_compile_in_same_configuration_packet(self):
        import test_final_native_references as cases
        import configuration_commit as commit
        import configuration_batch as batch
        helper=cases.FinalNativeReferenceTests();request,_,_,_,_=helper.case();self.addCleanup(helper.doCleanups)
        directory=Path(request['directory']);path=directory/'Configuration.xml';root=E.parse(path);children=root.getroot()[0].find(objects.Q+'ChildObjects')
        for case in self.samples():
            folder=directory/(case['kind']+'s');folder.mkdir(exist_ok=True);(folder/(case['name']+'.xml')).write_text(case['xml'],encoding='utf-8');E.SubElement(children,objects.Q+case['kind']).text=case['name']
            if case['kind']=='CommonModule':
                ext=folder/case['name']/'Ext';ext.mkdir(parents=True);(ext/'Module.bsl').write_bytes(b'Procedure Run() Export\r\nEndProcedure\r\nProcedure Alternate() Export\r\nEndProcedure\r\n')
        root.write(path,encoding='utf-8');plan,_=commit.prepare(request);request.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
        _,records=batch.read_packet(commit.serialize(request)['data']);records={row.object_id:row for row in records};module=self.samples()[0]
        for case in self.samples()[1:]:
            record=records[case['id']];relations=s.metadata_relations(s.Parser(record.metadata.decode('utf-8-sig')).documents()[0][14])
            self.assertNotIn(module['id'],relations)
            native_relations=s.metadata_relations(s.Parser(case['metadata']).documents()[0][14])
            self.assertEqual(set(relations.values()),set(native_relations.values()))
            self.assertEqual(s.render(s.Parser(s.inflate(record.body).decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))

    def test_module_deletion_checks_retained_job_body_without_descriptor_link(self):
        import external_dependencies as dependencies
        import native_version_fixture
        module,job=self.samples()[:2];metadata={row['id']:s.Parser(row['metadata']).documents() for row in (module,job)}
        bodies={row['id']:row['body'].encode('utf-8-sig') for row in (module,job)}
        request=dict(platform='8.5.1.1529',context=base64.b64encode(s.storage([s.text_bytes(docs) for docs in metadata.values()],s.text_bytes([[s.atom(0)]]))).decode(),storage=native_version_fixture.storage(metadata,bodies))
        self.assertTrue(dependencies.has_watchers(metadata))
        self.assertNotIn(module['id'],s.metadata_relations(metadata[job['id']][0][14]))
        with self.assertRaisesRegex(ValueError,'Final native property references deleted metadata'):
            dependencies.validate(request,metadata,{module['id']},{module['id']},{})
        target=s.Parser(job['body']).documents()[0];target[1][6]=s.atom('77777777-7777-4777-8777-777777777777')
        dependencies.validate(request,metadata,{module['id']},{module['id']},{job['id']:(copy.deepcopy(metadata[job['id']]),s.native_body_bytes([target]),[])})


if __name__=='__main__':unittest.main()
