"""Final native streams, including unchanged streams, protect deleted types."""
import base64,copy,json,unittest,uuid
from pathlib import Path
import test_metadata_dependencies as metadata_cases
from test_managed_form_creation import store
import external_dependencies as dependencies
import external_data
import metadata_context
import metadata_identifiers as ids
import native_metadata as s
import native_version_fixture


class ExternalDependencyTests(unittest.TestCase):
    def fixture(self):
        request,_,_,catalog,name,_=metadata_cases.DependencyTests().fixture();objects=metadata_context.context_objects(request['context'])
        form='cccccccc-cccc-4ccc-8ccc-cccccccccccc';docs=copy.deepcopy(objects[request['object_id']]);m=docs[0]
        m[1],m[2],m[9]=s.atom(form),s.atom(ids.class_id('CommonForm')),s.atom('References',True)
        m[13]=[s.atom(0)];m[11]=[s.atom(1),s.atom(form+'.0',True),s.atom(str(uuid.uuid4()))];objects[form]=docs
        m[14]=[s.atom(1),m[3],s.atom(1)]
        request['context']=base64.b64encode(s.storage([s.text_bytes(d) for d in objects.values()],s.text_bytes([[s.atom(0)]]))).decode()
        request['snapshots']={catalog:request['reference_snapshots'][catalog]}
        base=json.loads(Path(__file__).with_name('fixtures').joinpath('form_rules_851.json').read_text(encoding='utf-8'))['bases']['InputField']
        native=s.Parser(base).documents()[0];source_meta=objects[catalog][0];snapshot=base64.b64decode(request['snapshots'][catalog]);_,pos=s.read_record(snapshot,12);raw,_=s.read_record(snapshot,pos);body=s.inflate(raw)
        import native_references,metadata_targets,metadata_object_xml
        identity=next(row for row in metadata_targets.index(objects).targets if row.object_id==catalog)
        generated=native_references.generated_ids(body,identity,metadata_object_xml.profiles.layout('Catalog'))[2]
        native[3][2][5]=[s.atom('Pattern',True),[s.atom('#',True),s.atom(generated)]]
        raw_form=s.native_body_bytes([native]);request['storage']=native_version_fixture.storage(objects,{catalog:body},{form+'.0':raw_form})
        return request,objects,catalog,form,native,generated

    def test_unchanged_form_blocks_deleting_its_reference_type(self):
        request,objects,catalog,form,_,_=self.fixture()
        self.assertNotIn(catalog,s.metadata_relations(objects[form][0][14]))
        with self.assertRaisesRegex(ValueError,'Final external stream references deleted metadata'):dependencies.validate(request,objects,{catalog},{catalog},{})

    def test_replacing_the_stream_and_deleting_its_type_is_valid(self):
        request,objects,catalog,form,native,_=self.fixture();native[3][2][5]=[s.atom('Pattern',True),[s.atom('B',True)]]
        changed={form:(objects[form],b'form description',[(form+'.0',s.compress(s.native_body_bytes([native])))])}
        dependencies.validate(request,objects,{catalog},{catalog},changed)

    def test_role_rights_block_deletion_until_the_complete_file_is_replaced(self):
        request,objects,catalog,role,_,_=self.fixture()
        import metadata_identifiers,role_right_identifiers,role_rights_xml
        from test_role_rights_xml import source
        objects[role][0][2]=s.atom(metadata_identifiers.class_id('Role'))
        raw=('{10,{1,{{1,'+catalog+',0,0},{0,'+role_right_identifiers.right_id('Read')+',1}}},{0},4294967295,1,0,4294967295}').encode()
        owner_snapshot=base64.b64decode(request['snapshots'][catalog]);_,pos=s.read_record(owner_snapshot,12);body,_=s.read_record(owner_snapshot,pos)
        request['storage']=native_version_fixture.storage(objects,{catalog:s.inflate(body),role:b'role definition'},{role+'.0':raw})
        with self.assertRaisesRegex(ValueError,'Final external stream references deleted metadata'):
            dependencies.validate(request,objects,{catalog},{catalog},{})
        changed={role:(objects[role],b'role definition',[(role+'.0',s.compress(role_rights_xml.compile(source())))])}
        dependencies.validate(request,objects,{catalog},{catalog},changed)

    def test_missing_or_stale_storage_is_rejected(self):
        request,objects,catalog,form,_,_=self.fixture();missing=dict(request);missing.pop('storage')
        with self.assertRaisesRegex(ValueError,'require current version storage'):dependencies.validate(missing,objects,{catalog},{catalog},{})
        objects[form][0][11][2]=s.atom(str(uuid.uuid4()))
        with self.assertRaisesRegex(ValueError,'stream version mismatch'):dependencies.validate(request,objects,{catalog},{catalog},{})

    def test_guid_in_quoted_form_text_is_not_a_metadata_reference(self):
        _,_,_,_,native,guid=self.fixture();native[3][2][5]=[s.atom('Pattern',True),[s.atom('S',True),s.atom(10),s.atom(1)]]
        native[3][2][3]=s.atom(guid,True)
        self.assertNotIn(guid,dependencies.stream_ids('CommonForm',b'',s.native_body_bytes([native])))

    def test_bulk_version_lookup_matches_individual_reads(self):
        request,objects,_,_,_,_=self.fixture();data=base64.b64decode(request['storage']);many=external_data.extract_many(data,set(objects))
        self.assertEqual(many,{oid:external_data.extract(data,oid) for oid in objects})

    def test_schema_reference_type_is_found_but_binary_user_data_is_ignored(self):
        import schema_content
        data=json.loads(Path(__file__).with_name('fixtures').joinpath('template_packets_851.json').read_text(encoding='utf-8'))
        guid='dddddddd-dddd-4ddd-8ddd-dddddddddddd'
        raw=schema_content.convert(data['reference_request']['template_xml'],{'CatalogRef.CRSAPI_FullCatalog':guid},{})
        body=s.native_body_bytes([[s.atom(1),[s.atom(4),s.atom(0),s.atom(6)],s.atom(0)]])
        self.assertIn(guid,dependencies.stream_ids('CommonTemplate',body,raw))
        body=s.native_body_bytes([[s.atom(1),[s.atom(4),s.atom(0),s.atom(1)],s.atom(0)]])
        self.assertEqual(dependencies.stream_ids('CommonTemplate',body,guid.encode()),set())

    def test_tabular_row_type_is_protected_when_the_whole_owner_is_deleted(self):
        request,objects,catalog,form,native,_=self.fixture()
        snapshot=base64.b64decode(request['snapshots'][catalog]);_,pos=s.read_record(snapshot,12);raw,_=s.read_record(snapshot,pos)
        body=s.inflate(raw);owner=s.Parser(body.decode('utf-8-sig')).documents()[0]
        native[3][2][5]=[s.atom('Pattern',True),[s.atom('#',True),owner[5][2][0][1][3]]]
        request['storage']=native_version_fixture.storage(objects,{catalog:body},{form+'.0':s.native_body_bytes([native])})
        with self.assertRaisesRegex(ValueError,'Final external stream references deleted metadata'):dependencies.validate(request,objects,{catalog},{catalog},{})


if __name__=='__main__':unittest.main()
