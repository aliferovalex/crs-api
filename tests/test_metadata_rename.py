"""Explicit body renames match independent Designer imports, preserving IDs."""
import json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import metadata_object_xml as objects
import native_metadata as s
import xml_namespaces


class MetadataRenameTests(unittest.TestCase):
    def samples(self):
        return json.loads(Path(__file__).with_name('fixtures').joinpath('metadata_rename_851.json').read_text(encoding='utf-8'))['samples']

    def test_three_native_renames_preserve_every_other_body_field(self):
        for case in self.samples():
            with self.subTest(case=case['label']):
                source=s.Parser(case['source']).documents()[0];before=s.render(source)
                raw,_=objects.change(case['xml'],'8.5.1.1529','Catalog',source,allow_rename=True)
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))
                self.assertEqual(s.render(source),before)
                exported=objects.export(s.Parser(raw.decode('utf-8-sig')).documents()[0],{},'8.5.1.1529','Catalog')
                self.assertEqual(exported[0].findtext(objects.Q+'Properties/'+objects.Q+'Name'),case['name'])
                self.assertEqual(objects.create(xml_namespaces.serialize(exported),'8.5.1.1529','Catalog')[2],raw)

    def test_renaming_is_not_implicitly_enabled_in_packet_converters(self):
        case=self.samples()[0]
        with self.assertRaisesRegex(ValueError,'rename is unsupported'):
            objects.change(case['xml'],'8.5.1.1529','Catalog',s.Parser(case['source']).documents()[0])

    def test_explicit_rename_does_not_allow_another_uuid_or_generated_types(self):
        case=self.samples()[0];source=s.Parser(case['source']).documents()[0]
        top=E.fromstring(case['xml']);top[0].set('uuid','aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee')
        with self.assertRaisesRegex(ValueError,'UUID differs'):
            objects.change(xml_namespaces.serialize(top),'8.5.1.1529','Catalog',source,allow_rename=True)
        top=E.fromstring(case['xml']);node=top[0].find('.//{'+xml_namespaces.READABLE+'}TypeId');node.text='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
        with self.assertRaisesRegex(ValueError,'generated identifiers'):
            objects.change(xml_namespaces.serialize(top),'8.5.1.1529','Catalog',source,allow_rename=True)

    def test_missing_internal_info_preserves_original_generated_ids(self):
        case=self.samples()[0];top=E.fromstring(case['xml']);top[0].remove(top[0].find(objects.Q+'InternalInfo'))
        raw,_=objects.change(xml_namespaces.serialize(top),'8.5.1.1529','Catalog',s.Parser(case['source']).documents()[0],allow_rename=True)
        self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))

    def test_final_type_name_resolves_to_verified_source_generated_uuid(self):
        import test_object_change_serializer as source
        import metadata_context,metadata_targets,native_references
        case=self.samples()[0];old_xml=case['xml'].replace(case['name'],case['old_name'])
        request,docs,raw=source.fixture('Catalog',old_xml);oid=case['id']
        objects=metadata_context.context_objects(request['context'])
        final={oid:dict(kind='Catalog',name=case['name'],parent_id=s.val(docs[0][3]),path='Catalogs/'+case['name']+'.xml')}
        index=metadata_targets.final(objects,final,allow_rename=True);reader=native_references.Catalog(request,index)
        identity=reader.select('Catalog',case['name']);entry=reader.load(identity)
        self.assertEqual(entry.identity.name,case['old_name'])
        self.assertEqual(reader.type_id('Catalog',case['name']),s.val(s.Parser(raw.decode('utf-8-sig')).documents()[0][1][3]))
        with self.assertRaisesRegex(ValueError,'missing from current context'):
            reader.select('Catalog',case['old_name'])
        forged=native_references.Catalog(request,metadata_targets.Index(index.targets))
        with self.assertRaisesRegex(ValueError,'identity mismatch'):forged.load(identity)

    def test_final_index_does_not_authorize_an_owner_change(self):
        import test_object_change_serializer as source
        import metadata_context,metadata_targets
        case=self.samples()[0];request,_,_=source.fixture('Catalog',case['xml'].replace(case['name'],case['old_name']))
        final={case['id']:dict(kind='Catalog',name=case['name'],parent_id=s.ZERO,path='Catalogs/'+case['name']+'.xml')}
        with self.assertRaisesRegex(ValueError,'identity differs'):
            metadata_targets.final(metadata_context.context_objects(request['context']),final)

    def test_complete_export_commits_new_name_in_body_descriptor_and_graph(self):
        import base64,copy,shutil,tempfile,uuid
        import test_object_creation_serializer as source
        from test_managed_form_creation import store
        import configuration_commit as commit,configuration_export as export,configuration_batch as batch
        import metadata_context,metadata_identifiers as ids,configuration_xml
        case=self.samples()[0];seed=source.fixture('8.5.1.1529');root_id=seed['object_id'];oid=case['id'];q=objects.Q
        root_docs=metadata_context.context_objects(seed['context'])[root_id]
        _,pos=s.read_record(base64.b64decode(seed['snapshots'][root_id]),12)
        compressed,_=s.read_record(base64.b64decode(seed['snapshots'][root_id]),pos);body=s.Parser(s.inflate(compressed).decode('utf-8-sig')).documents()
        body[0][4]=[s.atom(0)];body[0].append([s.atom(ids.class_id('Catalog')),s.atom(1),s.atom(oid)])
        catalog=copy.deepcopy(root_docs);m=catalog[0]
        m[1]=s.atom(oid);m[2]=s.atom(ids.class_id('Catalog'));m[3]=s.atom(root_id);m[4]=s.atom(s.ZERO);m[9]=s.atom(case['old_name'],True);m[10]=s.atom(0)
        for slot in (11,12,13):m[slot]=[s.atom(0)]
        m[14]=[s.atom(1),s.atom(root_id),s.atom(1)]
        root_docs[0][12]=[s.atom(1),[s.atom(ids.class_id('Catalog')),s.atom(1),s.atom(oid)]]
        root_docs[0][14]=[s.atom(1),s.atom(oid),s.atom(1)]
        docs={root_id:root_docs,oid:catalog};common=configuration_xml.common_properties(body,root_id,'8.5.1.1529')
        with tempfile.TemporaryDirectory() as directory:
            old=Path(directory)/'old';new=Path(directory)/'new';(old/'Catalogs').mkdir(parents=True)
            top=E.Element(q+'MetaDataObject',version='2.21');cfg=E.SubElement(top,q+'Configuration',uuid=root_id);props=E.SubElement(cfg,q+'Properties')
            E.SubElement(props,q+'Name').text=s.val(common[2]);E.SubElement(props,q+'Comment').text=s.val(common[4]);children=E.SubElement(cfg,q+'ChildObjects');E.SubElement(children,q+'Catalog').text=case['old_name']
            (old/'Configuration.xml').write_text(xml_namespaces.serialize(top),encoding='utf-8')
            (old/'Catalogs'/(case['old_name']+'.xml')).write_text(case['xml'].replace(case['name'],case['old_name']),encoding='utf-8')
            info=E.Element(export.D+'ConfigDumpInfo',format='Hierarchical');versions=E.SubElement(info,export.D+'ConfigVersions')
            for key,value in docs.items():E.SubElement(versions,export.D+'Metadata',id=key,configVersion=uuid.UUID(s.val(value[0][8])).bytes_le.hex()+'00000000')
            (old/'ConfigDumpInfo.xml').write_bytes(E.tostring(info,encoding='utf-8'));shutil.copytree(old,new)
            children[0].text=case['name'];(new/'Configuration.xml').write_text(xml_namespaces.serialize(top),encoding='utf-8')
            (new/'Catalogs'/(case['old_name']+'.xml')).unlink();(new/'Catalogs'/(case['name']+'.xml')).write_text(case['xml'],encoding='utf-8')
            request=dict(directory=str(new),baseline_directory=str(old),platform='8.5.1.1529',repository='Synthetic',repository_version=str(uuid.uuid4()),
                         context=base64.b64encode(s.storage([s.text_bytes(value) for value in docs.values()],s.text_bytes([[s.atom(0)]]))).decode(),
                         snapshots={root_id:store(root_docs,s.native_body_bytes(body)),oid:store(catalog,case['source'].encode('utf-8-sig'))},
                         originals={key:uuid.UUID(s.val(value[0][7])).bytes_le.hex()+'00000000' for key,value in docs.items()})
            plan,_=commit.prepare(request);self.assertEqual(plan['removed_ids'],[]);self.assertEqual(plan['new_ids'],[])
            request.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
            result=commit.serialize(request);graph,records=batch.read_packet(result['data']);record=next(row for row in records if row.object_id==oid)
            self.assertEqual(s.render(s.Parser(s.inflate(record.body).decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))
            self.assertEqual(s.val(s.Parser(record.metadata.decode('utf-8-sig')).documents()[0][9]),case['name'])
            self.assertEqual(next(row for row in result['descriptions'] if row['id']==oid)['name'],case['name'])
            self.assertIn(case['name'],s.render(graph));self.assertNotIn(case['old_name']+'"',s.render(graph))
            self.assertEqual(result['changed_ids'],[oid,root_id])


if __name__=='__main__':unittest.main()
