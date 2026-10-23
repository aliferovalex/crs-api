"""A typed owner's verified dependencies must not prevent creating a form."""
import base64,copy,json,unittest,uuid
from pathlib import Path
from xml.etree import ElementTree as E
import test_catalog_form_serializer as cases
from test_managed_form_creation import store
from test_form_kinds_xml import common_xml
import inline_object_xml
import managed_form_operations as forms
import metadata_context
import metadata_identifiers as ids
import metadata_object_xml as metadata
import native_metadata as s
import native_version_fixture


class ParentDependencyTests(unittest.TestCase):
    def fixture(self):
        r=cases.fixture();objects=metadata_context.context_objects(r['context']);oid=r['object_id'];docs=objects[oid]
        fixture=json.loads(Path(__file__).with_name('fixtures').joinpath('metadata_reference_types_851.json').read_text(encoding='utf-8'))
        case=next(row for row in fixture['cases'] if row['kind']=='Catalog');other=E.fromstring(case['xml'])[0];other_id=other.get('uuid');name=other.findtext(metadata.Q+'Properties/'+metadata.Q+'Name')
        foreign=copy.deepcopy(docs);m=foreign[0];m[1]=s.atom(other_id);m[9]=s.atom(name,True)
        features=inline_object_xml.features(s.Parser(case['body']).documents()[0],metadata.profiles.layout('Catalog'));m[13]=[s.atom(len(features))]+[s.atom(v) for v in features]
        snapshot=base64.b64decode(r['snapshot']);_,pos=s.read_record(snapshot,12);raw,_=s.read_record(snapshot,pos);body=s.Parser(s.inflate(raw).decode('utf-8-sig')).documents()[0]
        top=metadata.export(body,{},r['platform'],'Catalog');children=top[0].find(metadata.Q+'ChildObjects');node=E.SubElement(children,metadata.Q+'Attribute',uuid=str(uuid.uuid4()));props=E.SubElement(node,metadata.Q+'Properties');E.SubElement(props,metadata.Q+'Name').text='Link'
        ref='cfg:CatalogRef.'+name;E.SubElement(E.SubElement(props,metadata.Q+'Type'),'{http://v8.1c.ru/8.1/data/core}Type').text=ref
        raw=metadata.object_xml(E.tostring(top,encoding='unicode'),r['platform'],'Catalog',type_references={ref:fixture['references'][ref]})[2]
        docs[0][13]=[s.atom(1),s.atom(node.get('uuid'))];docs[0][14]=[s.atom(2),docs[0][3],s.atom(other_id),s.atom(1),s.atom(0)]
        objects[other_id]=foreign;r['snapshot']=store(docs,raw);r['context']=base64.b64encode(s.storage([s.text_bytes(v) for v in objects.values()],s.text_bytes([[s.atom(0)]]))).decode()
        r['storage']=native_version_fixture.storage(objects,{oid:raw,other_id:case['body'].encode('utf-8-sig')});r['form_xml']=common_xml(())
        return r,objects,other_id,ref

    def test_source_reference_is_verified_and_preserved(self):
        r,objects,other,_=self.fixture();result=forms.create(r);_,_,_,_,owner,_=cases.records(result)
        self.assertEqual(s.metadata_relations(owner[0][14]),s.metadata_relations(objects[r['object_id']][0][14]));self.assertEqual(s.metadata_relations(owner[0][14])[other],0)

    def test_forged_live_relation_is_not_allowed(self):
        import external_data,test_object_xml_profiles
        r,objects,_,_=self.fixture();source=external_data.extract_many(base64.b64decode(r['storage']));bodies={oid:s.inflate(base64.b64decode(record['data'])) for oid,record in source.items()}
        oid='dddddddd-dddd-4ddd-8ddd-dddddddddddd';foreign=copy.deepcopy(next(iter(objects.values())));foreign[0][1]=s.atom(oid);foreign[0][9]=s.atom('Unrelated',True);foreign[0][13]=[s.atom(0)];objects[oid]=foreign
        top=E.fromstring(test_object_xml_profiles.xml('Catalog'));top[0].set('uuid',oid);top[0].find(metadata.Q+'Properties/'+metadata.Q+'Name').text='Unrelated';bodies[oid]=metadata.object_xml(E.tostring(top,encoding='unicode'),r['platform'],'Catalog')[2]
        m=objects[r['object_id']][0];relations=s.metadata_relations(m[14]);relations[oid]=0;m[14]=[s.atom(len(relations))]+[s.atom(k) for k in relations]+[s.atom(v) for v in relations.values()]
        data=base64.b64decode(r['snapshot']);_,pos=s.read_record(data,12);body,_=s.read_record(data,pos);r['snapshot']=store(objects[r['object_id']],s.inflate(body));r['context']=base64.b64encode(s.storage([s.text_bytes(v) for v in objects.values()],s.text_bytes([[s.atom(0)]]))).decode()
        r['storage']=native_version_fixture.storage(objects,bodies)
        with self.assertRaisesRegex(ValueError,'Invalid object parent relations'):forms.create(r)

    def test_missing_source_version_is_not_treated_as_a_valid_dependency(self):
        r,_,_,_=self.fixture();r.pop('storage')
        with self.assertRaisesRegex(ValueError,'snapshot is required'):forms.create(r)

    def test_stale_referenced_type_is_rejected(self):
        r,objects,other,_=self.fixture();objects[other][0][5]=s.atom(int(s.val(objects[other][0][5]))+1)
        r['context']=base64.b64encode(s.storage([s.text_bytes(v) for v in objects.values()],s.text_bytes([[s.atom(0)]]))).decode()
        with self.assertRaisesRegex(ValueError,'version storage/context mismatch'):forms.create(r)


if __name__=='__main__':unittest.main()
