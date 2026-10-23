"""Whole XDTO package files use the ordinary object creation/change pipelines."""
import base64,json,sys,tempfile,unittest,uuid,shutil,subprocess
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import object_file_content as files
import metadata_object_xml as metadata
import metadata_context
import preparation_plan
import native_metadata as s
import object_creation_serializer as creation
import object_change_serializer as change
import configuration_batch as batch
import configuration_commit as commit
import configuration_xml
import metadata_identifiers
import configuration_export as export
import test_configuration_export as export_cases
import metadata_identifiers as identifiers
import xml_namespaces
import test_object_xml_profiles as objects
import test_object_change_serializer as changes
from test_managed_form_creation import store


class ObjectFileContentTests(unittest.TestCase):
    def case(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('xdto_package_851.json').read_text(encoding='utf-8'))

    def test_metadata_and_complete_file_match_independent_compilation(self):
        case=self.case();_,_,raw,ids=metadata.create(case['xml'],'8.5.1.1529','XDTOPackage');self.assertEqual(raw.decode('utf-8-sig'),case['body']);self.assertEqual(ids,[])
        data=files.convert('XDTOPackage',case['xml'],{'Package':case['package']});self.assertEqual(data['Package'].data,base64.b64decode(case['package']))
        top=metadata.export(s.Parser(case['body']).documents()[0],{},'8.5.1.1529','XDTOPackage');self.assertEqual(metadata.create(E.tostring(top,encoding='unicode'),'8.5.1.1529','XDTOPackage')[2],raw)

    def test_creation_packet_contains_complete_companion_without_reformatting(self):
        case=self.case();request=objects.request('XDTOPackage');request.update(object_xml=case['xml'],file_data={'Package':case['package']})
        result=creation.serialize(request);_,records=batch.read_packet(result['data']);record=next(row for row in records if row.object_id==result['object_id'])
        self.assertEqual(s.inflate(record.body).decode('utf-8-sig'),case['body'])
        self.assertEqual({name:s.inflate(raw) for name,raw in record.externals},{record.object_id+'.0':base64.b64decode(case['package'])})

    def test_change_replaces_whole_file_and_preserves_unrelated_stream(self):
        case=self.case();request,docs,raw=changes.fixture('XDTOPackage',case['xml']);oid=request['object_id'];version=str(uuid.uuid4());other=oid+'.9';docs[0][11]=[s.atom(1),s.atom(other,True),s.atom(version)];docs[2]=[s.atom(0)]
        request.update(snapshot=store(docs,raw),context=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode())
        payload=base64.b64decode(case['package']).replace(b'name="Code"',b'name="LongCode"').replace(b'tns:Code',b'tns:LongCode')
        request['file_data']={'Package':base64.b64encode(payload).decode()};_,updated,body,storage,pos=changes.unpack(change.serialize(request))
        self.assertEqual(body,raw);self.assertEqual(s.val(updated[0][11][1]),other);self.assertEqual(base64.b64decode(s.val(updated[0][11][2])),uuid.UUID(version).bytes_le+bytes(4))
        external,_=s.read_record(storage,pos);self.assertEqual(s.inflate(external),payload)

    def test_common_preparation_reads_required_file_and_rejects_missing_companion(self):
        case=self.case();context=objects.request('XDTOPackage')['context']
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'XDTOPackages/CRSXDTO.xml';file.parent.mkdir();file.write_text(case['xml'],encoding='utf-8');companion=file.with_suffix('')/'Ext/Package.bin';companion.parent.mkdir(parents=True);companion.write_bytes(base64.b64decode(case['package']))
            request=dict(xml_path=str(file),context=context,platform='8.5.1.1529');plan=preparation_plan.plan(request)
            self.assertEqual(plan['kind'],'XDTOPackage');self.assertEqual(plan['file_data'],{'Package':case['package']});companion.unlink()
            with self.assertRaisesRegex(ValueError,'Missing companion file'):preparation_plan.plan(request)

    def test_invalid_file_data_namespace_and_unresolved_imports_fail_before_packing(self):
        case=self.case();raw=base64.b64decode(case['package'])
        invalid=[{}, {'Other.bin':case['package']},{'Package':'invalid!'},{'Package':base64.b64encode(raw.replace(b'urn:crs:types',b'urn:wrong')).decode()},
                 {'Package':base64.b64encode(b'<!DOCTYPE package><package/>').decode()}]
        for data in invalid:
            with self.subTest(data=list(data)),self.assertRaises(ValueError):files.convert('XDTOPackage',case['xml'],data)
        request=objects.request('XDTOPackage');request.update(object_xml=case['xml'],file_data={'Package':base64.b64encode(raw.replace(b'</package>',b'<import namespace="urn:another"/></package>')).decode()})
        with self.assertRaisesRegex(ValueError,'Unresolved XDTO package import'):creation.serialize(request)

    def test_complete_export_creation_carries_file_into_the_final_packet(self):
        case=self.case();seed=objects.request('XDTOPackage');context=metadata_context.context_objects(seed['context']);root=seed['object_id'];q=metadata.Q
        snapshot=base64.b64decode(seed['snapshots'][root]);_,pos=s.read_record(snapshot,12);raw,_=s.read_record(snapshot,pos);source=s.Parser(s.inflate(raw).decode('utf-8-sig')).documents()
        groups={}
        for child,cls in metadata_context.children(context[root][0]):groups.setdefault(cls,[]).append(child)
        for cls,children_ids in groups.items():source[0].append([s.atom(cls),s.atom(len(children_ids))]+[s.atom(child) for child in children_ids])
        source[0].append([s.atom(identifiers.class_id('WebService')),s.atom(0)])
        seed['snapshots'][root]=store(context[root],s.native_body_bytes(source))
        common=configuration_xml.common_properties(source,root,seed['platform'])
        with tempfile.TemporaryDirectory() as temp:
            old=Path(temp)/'old';old.mkdir();new=Path(temp)/'new';top=E.Element(q+'MetaDataObject',version='2.21');obj=E.SubElement(top,q+'Configuration',uuid=root);props=E.SubElement(obj,q+'Properties');E.SubElement(props,q+'Name').text=s.val(common[2]);children=E.SubElement(obj,q+'ChildObjects')
            for child,cls in metadata_context.children(context[root][0]):
                kind=metadata_identifiers.class_labels()[cls];name=s.val(context[child][0][9]);E.SubElement(children,q+kind).text=name;leaf=E.Element(q+'MetaDataObject',version='2.21');node=E.SubElement(leaf,q+kind,uuid=child);E.SubElement(E.SubElement(node,q+'Properties'),q+'Name').text=name;file=old/(kind+'s')/(name+'.xml');file.parent.mkdir();file.write_bytes(E.tostring(leaf,encoding='utf-8'))
            (old/'Configuration.xml').write_bytes(E.tostring(top,encoding='utf-8'));d='{http://v8.1c.ru/8.3/xcf/dumpinfo}';dump=E.Element(d+'ConfigDumpInfo',format='Hierarchical');versions=E.SubElement(dump,d+'ConfigVersions')
            for oid,docs in context.items():E.SubElement(versions,d+'Metadata',id=oid,configVersion=uuid.UUID(s.val(docs[0][8])).bytes_le.hex()+'00000000')
            (old/'ConfigDumpInfo.xml').write_bytes(E.tostring(dump,encoding='utf-8'));shutil.copytree(old,new);E.SubElement(children,q+'XDTOPackage').text='CRSXDTO';(new/'Configuration.xml').write_bytes(E.tostring(top,encoding='utf-8'));file=new/'XDTOPackages/CRSXDTO.xml';file.parent.mkdir();file.write_text(case['xml'],encoding='utf-8');companion=file.with_suffix('')/'Ext/Package.bin';companion.parent.mkdir(parents=True);companion.write_bytes(base64.b64decode(case['package']))
            web=json.loads(Path(__file__).with_name('fixtures').joinpath('web_demo_types_851.json').read_text(encoding='utf-8'));original_name=E.fromstring(web['package_xml'])[0].findtext(q+'Properties/'+q+'Name');web_xml=web['xml'].replace('XDTOPackage.'+original_name,'XDTOPackage.CRSXDTO');web_id=E.fromstring(web_xml)[0].get('uuid')
            web_top,scopes=xml_namespaces.parse(web_xml)
            for tag,name in [('XDTOReturningValueType','Message'),('XDTOValueType','Code')]:
                value=web_top.find('.//'+q+tag);value.text='user:'+name;value.set('xmlns:user','urn:crs:types')
            web_xml=xml_namespaces.render(web_top,web_xml,scopes)
            dependent_id='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';dependent_xml=case['xml'].replace(E.fromstring(case['xml'])[0].get('uuid'),dependent_id).replace('CRSXDTO','DependentTypes').replace('urn:crs:types','urn:dependent')
            E.SubElement(children,q+'XDTOPackage').text='DependentTypes';dependent_file=new/'XDTOPackages/DependentTypes.xml';dependent_file.write_text(dependent_xml,encoding='utf-8');dependent_data=dependent_file.with_suffix('')/'Ext/Package.bin';dependent_data.parent.mkdir(parents=True);dependent_data.write_bytes(base64.b64decode(case['package']).replace(b'urn:crs:types',b'urn:dependent'))
            companion.write_bytes(companion.read_bytes().replace(b'</package>',b'<import namespace="urn:dependent"/></package>'));expected_package_bytes=companion.read_bytes()
            web_top,scopes=xml_namespaces.parse(web_xml);value=web_top.find('.//'+q+'XDTOValueType');value.set('xmlns:user','urn:dependent');web_xml=xml_namespaces.render(web_top,web_xml,scopes)
            E.SubElement(children,q+'WebService').text='MAExchange';(new/'Configuration.xml').write_bytes(E.tostring(top,encoding='utf-8'));web_file=new/'WebServices/MAExchange.xml';web_file.parent.mkdir();web_file.write_text(web_xml,encoding='utf-8');module=web_file.with_suffix('')/'Ext/Module.bsl';module.parent.mkdir(parents=True);module.write_text('// complete service module\n',encoding='utf-8')
            request=dict(seed,directory=str(new),baseline_directory=str(old),originals={oid:uuid.UUID(s.val(docs[0][7])).bytes_le.hex()+'00000000' for oid,docs in context.items()})
            plan,_=commit.prepare(request);request.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint']);result=commit.serialize(request)
            _,records=batch.read_packet(result['data']);oid=E.fromstring(case['xml'])[0].get('uuid');record=next(row for row in records if row.object_id==oid)
            self.assertEqual(set(result['new_ids']),{oid,web_id,dependent_id});self.assertEqual(s.inflate(dict(record.externals)[oid+'.0']),expected_package_bytes)
            package_docs=s.Parser(record.metadata.decode('utf-8-sig')).documents();self.assertEqual(s.metadata_relations(package_docs[0][14])[dependent_id],0)
            web_record=next(row for row in records if row.object_id==web_id);web_docs=s.Parser(web_record.metadata.decode('utf-8-sig')).documents();self.assertEqual(s.metadata_relations(web_docs[0][14])[oid],0)
            web_body=s.Parser(s.inflate(web_record.body).decode('utf-8-sig')).documents()[0];self.assertEqual([s.val(value) for value in web_body[3][2][0][2]],['0','urn:crs:types','Message'])
            self.assertEqual([s.val(value) for value in web_body[3][2][2][2][0][2]],['0','urn:dependent','Code'])

    def test_complete_export_detects_file_only_change_and_rejects_file_removal(self):
        case=self.case();fixture=export_cases.ConfigurationExportTests();fixture.setUp();self.addCleanup(fixture.doCleanups);context=fixture.objects;root=next(oid for oid,docs in context.items() if s.val(docs[0][3])==s.ZERO)
        _,docs,_=changes.fixture('XDTOPackage',case['xml']);m=docs[0];oid=s.val(m[1]);cls=metadata_identifiers.class_id('XDTOPackage');version=str(uuid.uuid4());m[3]=s.atom(root);m[14]=[s.atom(1),s.atom(root),s.atom(1)];m[11]=[s.atom(1),s.atom(oid+'.0',True),s.atom(version)];context[oid]=docs
        context[root][0][12].append([s.atom(cls),s.atom(1),s.atom(oid)]);context[root][0][12][0]=s.atom(len(context[root][0][12])-1)
        fixture.context=base64.b64encode(s.storage([s.text_bytes(value) for value in context.values()],s.text_bytes([[s.atom(0)]]))).decode()
        for directory in (fixture.old,fixture.new):
            file=directory/'Configuration.xml';top=E.parse(file);E.SubElement(top.getroot()[0].find(metadata.Q+'ChildObjects'),metadata.Q+'XDTOPackage').text='CRSXDTO';top.write(file,encoding='utf-8')
            file=directory/'XDTOPackages/CRSXDTO.xml';file.parent.mkdir();file.write_text(case['xml'],encoding='utf-8');companion=file.with_suffix('')/'Ext/Package.bin';companion.parent.mkdir(parents=True);companion.write_bytes(base64.b64decode(case['package']))
        dump=fixture.old/'ConfigDumpInfo.xml';top=E.parse(dump);parent=top.getroot();E.SubElement(parent,export.D+'Metadata',id=oid,configVersion=uuid.UUID(s.val(m[8])).bytes_le.hex()+'00000000');E.SubElement(parent,export.D+'Metadata',id=oid+'.0',configVersion=uuid.UUID(version).bytes_le.hex()+'00000000');top.write(dump,encoding='utf-8')
        companion=fixture.new/'XDTOPackages/CRSXDTO/Ext/Package.bin';companion.write_bytes(companion.read_bytes().replace(b'name="Code"',b'name="LongCode"').replace(b'tns:Code',b'tns:LongCode'))
        plan=fixture.plan();self.assertEqual(len(plan['operations']),1);self.assertEqual(plan['operations'][0]['object_id'],oid);self.assertEqual(plan['operations'][0]['changed_files'],['XDTOPackages/CRSXDTO/Ext/Package.bin'])
        companion.unlink()
        with self.assertRaisesRegex(ValueError,'Removed companion needs an explicit final content'):fixture.plan()

    def test_onescript_reads_profiles_and_roundtrips_the_python_file_plan(self):
        executable=shutil.which('oscript') or r'C:\Program Files\OneScript\bin\oscript.exe'
        if not Path(executable).is_file():self.skipTest('OneScript is not installed')
        case=self.case()
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);file=base/'CRSXDTO.xml';file.write_text(case['xml'],encoding='utf-8');companion=file.with_suffix('')/'Ext/Package.bin';companion.parent.mkdir(parents=True);companion.write_bytes(base64.b64decode(case['package']))
            source=base/'input.json';target=base/'output.json';source.write_text(json.dumps(dict(xml_path=str(file),context=objects.request('XDTOPackage')['context'],python=sys.executable)),encoding='utf-8')
            command=[executable,str(Path(__file__).with_name('check-object-files.os')),str(source),str(target)]
            result=subprocess.run(command,cwd=Path(__file__).resolve().parents[1],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout.decode('utf-8',errors='replace'));self.assertEqual(json.loads(target.read_text(encoding='utf-8-sig'))['file_data'],{'Package':case['package']})

    def test_onescript_validates_new_file_streams_for_both_codecs(self):
        executable=shutil.which('oscript') or r'C:\Program Files\OneScript\bin\oscript.exe'
        if not Path(executable).is_file():self.skipTest('OneScript is not installed')
        result=subprocess.run([executable,str(Path(__file__).with_name('check-created-file-streams.os'))],
                              cwd=Path(__file__).resolve().parents[1],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout.decode('utf-8',errors='replace'))


if __name__=='__main__':unittest.main()
