"""Defined types share generated identities and complete Type conversion."""
import base64
import copy
import json
from pathlib import Path
import sys
import unittest
from xml.etree import ElementTree as E
sys.path.insert(0,str(next(p for p in (Path(__file__).resolve().parents[1]/'src').iterdir() if (p/'metadata_object_xml.py').exists())))
import metadata_object_xml as objects
import metadata_type_references as refs
import object_xml_profiles as profiles
import native_metadata as s
import native_references
import metadata_targets
import metadata_identifiers as ids
import metadata_context
from test_managed_form_creation import store


class DefinedTypeTests(unittest.TestCase):
    def samples(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('defined_type_851.json').read_text())['samples']

    def test_scalar_and_composite_types_match_independent_native_bodies(self):
        for case in self.samples()[:2]:
            with self.subTest(name=case['name']):
                oid,name,body,generated=objects.create(case['xml'],'8.5.1.1529','DefinedType')
                self.assertEqual((oid,name),(case['id'],case['name']));self.assertEqual(len(generated),2)
                self.assertEqual(s.render(s.Parser(body.decode('utf-8-sig')).documents()[0]),s.render(s.Parser(case['body']).documents()[0]))
                exported=objects.export(s.Parser(case['body']).documents()[0],{},'8.5.1.1529','DefinedType')
                self.assertEqual(objects.create(E.tostring(exported,encoding='unicode'),'8.5.1.1529','DefinedType')[2],body)

    def test_alias_reference_uses_generated_type_id_instead_of_metadata_uuid(self):
        alias,_,parameter=self.samples()
        allocation=objects.allocate_creation(alias['xml'],'8.5.1.1529','DefinedType')
        # The ordinary reference resolver recognizes a configurable prefix and
        # category; allocation is available before dependent bodies are compiled.
        self.assertEqual(refs.reference_name('cfg:DefinedType.ProbeAlias'),('DefinedType','ProbeAlias'))
        self.assertEqual(profiles.reference_type('DefinedType'),('DefinedType','DefinedType'))
        self.assertNotEqual(allocation.generated[0],alias['id'])
        body=objects.create(parameter['xml'],'8.5.1.1529','SessionParameter',type_references={'cfg:DefinedType.ProbeAlias':allocation.generated[0]})[2]
        self.assertEqual(s.render(s.Parser(body.decode('utf-8-sig')).documents()[0]),s.render(s.Parser(parameter['body']).documents()[0]))
        exported=objects.export(s.Parser(parameter['body']).documents()[0],{},'8.5.1.1529','SessionParameter',type_references={'cfg:DefinedType.ProbeAlias':allocation.generated[0]})
        self.assertIsNotNone(exported.find('.//{http://v8.1c.ru/8.1/data/core}TypeSet'))
        self.assertEqual(objects.create(E.tostring(exported,encoding='unicode'),'8.5.1.1529','SessionParameter',type_references={'cfg:DefinedType.ProbeAlias':allocation.generated[0]})[2],body)

    def test_existing_alias_resolves_from_verified_snapshot(self):
        import test_constant_change as source
        request,docs,_=source.ConstantChangeTests().fixture()
        alias,_,parameter=self.samples();docs=copy.deepcopy(docs);m=docs[0]
        m[1]=s.atom(alias['id']);m[2]=s.atom(ids.class_id('DefinedType'));m[9]=s.atom(alias['name'],True)
        m[13]=[s.atom(0)]
        request.update(platform='8.5.1.1529',context=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode(),
                       reference_snapshots={alias['id']:store(docs,alias['body'].encode('utf-8-sig'))})
        generated=objects.allocate_creation(alias['xml'],request['platform'],'DefinedType').generated[0]
        self.assertEqual(refs.resolve(parameter['xml'],request),{'cfg:DefinedType.ProbeAlias':generated})
        request['reference_snapshots']={}
        with self.assertRaisesRegex(ValueError,'snapshot is required'):refs.resolve(parameter['xml'],request)

    def test_forward_alias_declaration_resolves_before_compilation(self):
        import test_constant_change as source
        request,_,_=source.ConstantChangeTests().fixture();request['platform']='8.5.1.1529'
        alias,_,parameter=self.samples();allocation=objects.allocate_creation(alias['xml'],request['platform'],'DefinedType')
        targets=metadata_targets.creation('DefinedType',alias['id'],alias['name'],{},metadata_context.context_objects(request['context']))
        reader=native_references.Catalog(request,targets);reader.declare(allocation)
        resolved=refs.resolve(parameter['xml'],dict(request,_native_references=reader))
        self.assertEqual(resolved,{'cfg:DefinedType.ProbeAlias':allocation.generated[0]})
        body=objects.create(alias['xml'],request['platform'],'DefinedType',allocation=allocation)[2]
        reader.register(alias['id'],body,[])
        self.assertEqual(refs.resolve(parameter['xml'],dict(request,_native_references=reader)),resolved)

    def test_configuration_packet_contains_aliases_and_dependent_parameter(self):
        import test_final_native_references as cases
        import configuration_commit as commit
        import configuration_batch as batch
        helper=cases.FinalNativeReferenceTests();request,_,_,_,_=helper.case();self.addCleanup(helper.doCleanups)
        directory=Path(request['directory']);rootfile=directory/'Configuration.xml';root=E.parse(rootfile)
        children=root.getroot()[0].find(objects.Q+'ChildObjects')
        # Put the dependent declaration first: compilation must use the final
        # declaration index rather than filesystem or XML declaration order.
        samples=self.samples();samples=[samples[2],samples[0],samples[1]]
        for case in samples:
            folder=directory/profiles.profiles()[case['kind']]['folder'];folder.mkdir(exist_ok=True)
            (folder/(case['name']+'.xml')).write_text(case['xml'],encoding='utf-8')
            E.SubElement(children,objects.Q+case['kind']).text=case['name']
        root.write(rootfile,encoding='utf-8')
        plan,_=commit.prepare(request)
        request.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
        result=commit.serialize(request);_,records=batch.read_packet(result['data']);records={row.object_id:row for row in records}
        for case in samples:
            body=s.Parser(s.inflate(records[case['id']].body).decode('utf-8-sig')).documents()[0]
            self.assertEqual(s.render(body),s.render(s.Parser(case['body']).documents()[0]))
        relations=s.metadata_relations(s.Parser(records[samples[0]['id']].metadata.decode('utf-8-sig')).documents()[0][14])
        self.assertEqual(relations[samples[1]['id']],0)

    def test_defined_type_requires_typeset_xml_element(self):
        alias,_,parameter=self.samples()
        invalid=parameter['xml'].replace('v8:TypeSet','v8:Type')
        with self.assertRaisesRegex(ValueError,'TypeSet'):
            objects.create(invalid,'8.5.1.1529','SessionParameter',type_references={'cfg:DefinedType.ProbeAlias':alias['id']})

    def test_change_rebuilds_whole_type_and_preserves_generated_ids(self):
        alias,composite,_=self.samples();source=s.Parser(alias['body']).documents()[0]
        target=E.fromstring(alias['xml']);props=target[0].find(objects.Q+'Properties')
        props.remove(props.find(objects.Q+'Type'))
        props.append(E.fromstring(composite['xml'])[0].find(objects.Q+'Properties/'+objects.Q+'Type'))
        target[0].remove(target[0].find(objects.Q+'InternalInfo'))
        result=objects.change(E.tostring(target,encoding='unicode'),'8.5.1.1529','DefinedType',source)
        raw=result[0];body=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        self.assertEqual([s.val(body[1][i]) for i in (1,2)],[s.val(source[1][i]) for i in (1,2)])
        pattern=objects.at(body,profiles.layout('DefinedType')['type_path'])
        expected=objects.at(s.Parser(composite['body']).documents()[0],profiles.layout('DefinedType')['type_path'])
        self.assertEqual(s.render(pattern),s.render(expected))


if __name__=='__main__':unittest.main()
