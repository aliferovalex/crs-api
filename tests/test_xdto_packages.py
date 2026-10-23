"""Package declarations, imports and version-bound custom type catalogs."""
import base64,copy,json,sys,unittest,uuid
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import xdto_packages as packages
import xdto_type_xml
import metadata_object_xml as metadata
import native_metadata as s
import metadata_context
import metadata_targets
import native_references
import preparation_plan
import metadata_identifiers as ids
import xml_namespaces
import object_change_serializer as change
import test_object_change_serializer as changes
import native_version_fixture
import test_configuration_export as export_cases
import configuration_commit
from test_managed_form_creation import store


class XDTOPackageTests(unittest.TestCase):
    def case(self):return json.loads(Path(__file__).with_name('fixtures').joinpath('xdto_package_851.json').read_text(encoding='utf-8'))

    def declaration(self,namespace='urn:crs:types',imports=(),oid=None):
        case=self.case();definition=case['xml'];raw=base64.b64decode(case['package'])
        if namespace!='urn:crs:types':definition=definition.replace('urn:crs:types',namespace);raw=raw.replace(b'urn:crs:types',namespace.encode())
        if oid:definition=definition.replace(E.fromstring(definition)[0].get('uuid'),oid).replace('CRSXDTO','OtherPackage')
        for uri in imports:raw=raw.replace(b'</package>',('<import namespace="'+uri+'"/></package>').encode())
        return definition,raw,packages.declaration(definition,raw)

    def test_whole_file_declarations_and_transitive_imports(self):
        _,_,one=self.declaration(imports=('urn:other',));_,_,two=self.declaration('urn:other',oid='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')
        catalog=packages.Catalog([one,two]);catalog.validate();available=catalog.available([one.object_id])
        self.assertEqual(catalog.dependencies(one.object_id),{two.object_id});self.assertEqual(available['urn:crs:types'],frozenset({'Code','Message'}));self.assertIn('Message',available['urn:other'])
        value=E.fromstring('<Type xmlns:t="urn:other">t:Message</Type>');self.assertEqual([s.val(n) for n in xdto_type_xml.read(value,{'t':'urn:other'},available)],['0','urn:other','Message'])
        with self.assertRaisesRegex(ValueError,'Unsupported or unbound'):xdto_type_xml.read(value,{'t':'urn:other'},catalog.available([]))

    def test_import_cycles_are_traversed_once(self):
        _,_,one=self.declaration(imports=('urn:other',));_,_,two=self.declaration('urn:other',('urn:crs:types',),'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');catalog=packages.Catalog([one,two]);catalog.validate()
        self.assertIn('urn:other',catalog.available([one.object_id]));self.assertIn('urn:crs:types',catalog.available([two.object_id]))

    def test_missing_import_duplicate_namespace_and_duplicate_type_fail(self):
        definition,raw,one=self.declaration(imports=('urn:missing',))
        with self.assertRaisesRegex(ValueError,'Unresolved XDTO package import'):packages.Catalog([one]).validate()
        with self.assertRaisesRegex(ValueError,'Ambiguous XDTO package namespace'):packages.Catalog([one,self.declaration(oid='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')[2]])
        with self.assertRaisesRegex(ValueError,'duplicate XDTO type'):packages.declaration(definition,raw.replace(b'</package>',b'<valueType name="Code" base="xs:string"/></package>'))

    def source(self):
        definition,raw,package=self.declaration();request,docs,body=changes.fixture('XDTOPackage',definition);oid=request['object_id'];version=str(uuid.uuid4());docs[0][11]=[s.atom(1),s.atom(oid+'.0',True),s.atom(version)];docs[2]=[s.atom(0)]
        objects={oid:docs};request.update(context=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode(),snapshot=store(docs,body),file_data={'Package':base64.b64encode(raw).decode()})
        request['storage']=native_version_fixture.storage(objects,{oid:body},{oid+'.0':raw})
        return request,docs,body,raw

    def web(self):
        request,docs,body=changes.fixture('WebService');top,scopes=xml_namespaces.parse(request['object_xml']);q=metadata.Q;props=top[0].find(q+'Properties');selected=E.SubElement(props,q+'XDTOPackages',{'xmlns:mdref':xml_namespaces.READABLE});xr='{'+xml_namespaces.READABLE+'}'
        item=E.SubElement(selected,xr+'Item');E.SubElement(item,xr+'Presentation');E.SubElement(item,xr+'CheckState').text='0';E.SubElement(item,xr+'Value',{'{http://www.w3.org/2001/XMLSchema-instance}type':'mdref:MDObjectRef'}).text='XDTOPackage.CRSXDTO'
        children=top[0].find(q+'ChildObjects');operation=E.SubElement(children,q+'Operation',uuid='dddddddd-dddd-4ddd-8ddd-dddddddddddd');properties=E.SubElement(operation,q+'Properties');E.SubElement(properties,q+'Name').text='Run';E.SubElement(properties,q+'XDTOReturningValueType',{'xmlns:user':'urn:crs:types'}).text='user:Code';E.SubElement(properties,q+'ProcedureName').text='Run';E.SubElement(operation,q+'ChildObjects')
        return request,docs,body,xml_namespaces.render(top,request['object_xml'],scopes)

    def test_existing_package_catalog_checks_object_and_stream_versions(self):
        request,docs,_,_=self.source();catalog=packages.from_storage(request);self.assertIn('Code',catalog.available([request['object_id']])['urn:crs:types'])
        for slot in (5,8,11):
            altered=copy.deepcopy(docs)
            if slot==5:altered[0][5]=s.atom(int(s.val(altered[0][5]))+1)
            elif slot==8:altered[0][8]=s.atom(str(uuid.uuid4()))
            else:altered[0][11][2]=s.atom(str(uuid.uuid4()))
            modified=dict(request,context=base64.b64encode(s.storage([s.text_bytes(altered)],s.text_bytes([[s.atom(0)]]))).decode())
            with self.subTest(slot=slot),self.assertRaisesRegex(ValueError,'XDTO.*context mismatch'):packages.from_storage(modified)

    def test_source_file_reader_does_not_substitute_a_compiled_target_body(self):
        request,_,body,raw=self.source();reader=native_references.Catalog(request);identity=reader.select('XDTOPackage','CRSXDTO');modified=body.replace(b'urn:crs:types',b'urn:final:types');reader.register(identity.object_id,modified,[])
        self.assertEqual(reader.load(identity).body,modified)
        source=reader.source_files([identity],base64.b64decode(request['storage']))[identity.object_id]
        self.assertEqual(source.body,body);self.assertEqual(source.files[identity.object_id+'.0'],raw)

    def test_referenced_package_content_change_requires_complete_export(self):
        request,docs,body,raw=self.source();dependent=copy.deepcopy(docs);did='cccccccc-cccc-4ccc-8ccc-cccccccccccc';dependent[0][1]=s.atom(did);dependent[0][2]=s.atom(ids.class_id('WebService'));dependent[0][14]=[s.atom(1),s.atom(request['object_id']),s.atom(0)];dependent[0][11]=[s.atom(0)]
        request['context']=base64.b64encode(s.storage([s.text_bytes(docs),s.text_bytes(dependent)],s.text_bytes([[s.atom(0)]]))).decode()
        self.assertTrue(packages.needs_storage(request['object_xml'],request['context']))
        # Identical bytes still permit a metadata-only update of the package.
        packages.for_package(request,request['object_xml'],request['file_data'])
        request['file_data']={'Package':base64.b64encode(raw.replace(b'name="Code"',b'name="OtherCode"').replace(b'tns:Code',b'tns:OtherCode')).decode()}
        with self.assertRaisesRegex(ValueError,'referenced XDTO package require a complete export'):packages.for_package(request,request['object_xml'],request['file_data'])

    def test_existing_web_change_resolves_user_type_from_verified_package_stream(self):
        package_request,package,_,_=self.source();request,docs,body,target=self.web();objects={request['object_id']:docs,package_request['object_id']:package}
        request.update(context=base64.b64encode(s.storage([s.text_bytes(value) for value in objects.values()],s.text_bytes([[s.atom(0)]]))).decode(),object_xml=target,storage=package_request['storage'])
        self.assertTrue(packages.needs_storage(target,request['context']));_,updated,raw,_,_=changes.unpack(change.serialize(request));native=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        self.assertEqual([s.val(value) for value in native[3][2][0][2]],['0','urn:crs:types','Code']);self.assertEqual(s.metadata_relations(updated[0][14])[package_request['object_id']],0)

    def test_import_removal_drops_only_the_proven_source_dependency(self):
        request,docs,body,base=self.source();definition,other_raw,other=self.declaration('urn:other',oid='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');old=base.replace(b'</package>',b'<import namespace="urn:other"/></package>');parent=s.val(docs[0][3])
        dependency=copy.deepcopy(docs);m=dependency[0];m[1]=s.atom(other.object_id);m[9]=s.atom(other.name,True);m[11]=[s.atom(1),s.atom(other.object_id+'.0',True),s.atom(str(uuid.uuid4()))];m[14]=[s.atom(1),s.atom(parent),s.atom(1)]
        docs[0][14]=[s.atom(2),s.atom(parent),s.atom(other.object_id),s.atom(1),s.atom(0)];objects={request['object_id']:docs,other.object_id:dependency}
        request.update(context=base64.b64encode(s.storage([s.text_bytes(value) for value in objects.values()],s.text_bytes([[s.atom(0)]]))).decode(),snapshot=store(docs,body),storage=native_version_fixture.storage(objects,{request['object_id']:body,other.object_id:metadata.create(definition,request['platform'],'XDTOPackage')[2]},{request['object_id']+'.0':old,other.object_id+'.0':other_raw}))
        _,updated,_,_,_=changes.unpack(change.serialize(request));self.assertNotIn(other.object_id,s.metadata_relations(updated[0][14]));self.assertEqual(s.metadata_relations(updated[0][14])[parent],1)

    def test_complete_export_rejects_removing_a_type_used_by_unchanged_service(self):
        fixture=export_cases.ConfigurationExportTests();fixture.setUp();self.addCleanup(fixture.doCleanups);request,package,_,raw=self.source();web_request,web,_,web_xml=self.web();objects=fixture.objects;root=next(oid for oid,docs in objects.items() if s.val(docs[0][3])==s.ZERO)
        for docs in (package,web):docs[0][3]=s.atom(root);docs[0][14]=[s.atom(1),s.atom(root),s.atom(1)];objects[s.val(docs[0][1])]=docs
        web[0][14]=[s.atom(2),s.atom(root),s.atom(request['object_id']),s.atom(1),s.atom(0)];fixture.context=base64.b64encode(s.storage([s.text_bytes(value) for value in objects.values()],s.text_bytes([[s.atom(0)]]))).decode()
        for directory in (fixture.old,fixture.new):
            root_file=directory/'Configuration.xml';top=E.parse(root_file);children=top.getroot()[0].find(metadata.Q+'ChildObjects')
            for kind,docs,definition in [('XDTOPackage',package,request['object_xml']),('WebService',web,web_xml)]:
                E.SubElement(children,metadata.Q+kind).text=s.val(docs[0][9]);file=directory/(kind+'s')/(s.val(docs[0][9])+'.xml');file.parent.mkdir(exist_ok=True);file.write_text(definition,encoding='utf-8')
                if kind=='XDTOPackage':companion=file.with_suffix('')/'Ext/Package.bin';companion.parent.mkdir(parents=True);companion.write_bytes(raw)
            top.write(root_file,encoding='utf-8')
        root_meta=objects[root][0]
        for docs in (package,web):root_meta[12].append([docs[0][2],s.atom(1),docs[0][1]])
        root_meta[12][0]=s.atom(len(root_meta[12])-1);fixture.context=base64.b64encode(s.storage([s.text_bytes(value) for value in objects.values()],s.text_bytes([[s.atom(0)]]))).decode()
        dump=fixture.old/'ConfigDumpInfo.xml';top=E.parse(dump);d='{http://v8.1c.ru/8.3/xcf/dumpinfo}'
        for docs in (package,web):
            m=docs[0];E.SubElement(top.getroot(),d+'Metadata',id=s.val(m[1]),configVersion=uuid.UUID(s.val(m[8])).bytes_le.hex()+'00000000')
            for i in range(1,len(m[11]),2):E.SubElement(top.getroot(),d+'Metadata',id=s.val(m[11][i]),configVersion=uuid.UUID(s.val(m[11][i+1])).bytes_le.hex()+'00000000')
        top.write(dump,encoding='utf-8');file=fixture.new/'XDTOPackages/CRSXDTO/Ext/Package.bin';file.write_bytes(raw.replace(b'name="Code"',b'name="OtherCode"').replace(b'tns:Code',b'tns:OtherCode'))
        with self.assertRaisesRegex(ValueError,'Final WebService references a missing XDTO type'):configuration_commit.prepare(dict(directory=str(fixture.new),baseline_directory=str(fixture.old),context=fixture.context,platform='8.5.1.1529'))


if __name__=='__main__':unittest.main()
