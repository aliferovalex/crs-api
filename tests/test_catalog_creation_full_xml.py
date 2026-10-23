"""A new Catalog carries its complete inline XML in a single creation packet."""
import base64,hashlib,unittest
from xml.etree import ElementTree as E
import test_catalog_serializer as fixture
import test_tabular_section_xml as tables
import inline_object_xml
import metadata_object_xml
import object_xml_profiles
import metadata_object_xml as catalog
import metadata_identifiers
import xml_namespaces
import object_creation_serializer as c
import native_metadata as s
import test_managed_form_xml as form_fixture
import managed_form_xml as form_xml

FIDS=['88888888-8888-4888-8888-888888888880','88888888-8888-4888-8888-888888888881']


def forms_request():
    root=E.fromstring(xml());inputs=[]
    for i,fid in enumerate(FIDS):
        name='NewForm'+str(i);E.SubElement(root[0].find(catalog.Q+'ChildObjects'),catalog.Q+'Form').text=name
        definition='<MetaDataObject xmlns="'+xml_namespaces.MD+'" version="2.21"><Form uuid="'+fid+'"><Properties><Name>'+name+'</Name></Properties></Form></MetaDataObject>'
        inputs.append(dict(name=name,definition_xml=definition,form_xml=form_fixture.xml(),module_text='// Module '+str(i)))
    r=request(E.tostring(root,encoding='unicode'));r['forms']=inputs
    return r


def xml():
    root=E.fromstring(fixture.xml())
    root[0].find(catalog.Q+'ChildObjects').append(tables.section())
    return E.tostring(root,encoding='unicode')


def request(text):
    r=fixture.const.fixture('8.5.1.1529');rid=r['object_id']
    data=base64.b64decode(r['snapshots'][rid]);meta,pos=s.read_record(data,12);compressed,pos=s.read_record(data,pos)
    docs=s.Parser(s.inflate(compressed).decode('utf-8-sig')).documents()
    docs[0].append([s.atom(metadata_identifiers.class_id('Catalog')),s.atom(0)])
    body=s.compress(s.text_bytes(docs));m=s.Parser(meta.decode('utf-8-sig')).documents()[0]
    manifest=s.text_bytes([[s.atom(0),s.atom(1),m[1],s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(body).hexdigest(),True),s.atom(0)]])
    r['snapshots'][rid]=base64.b64encode(s.storage([meta,body],manifest)).decode()
    r.update(object_type='Catalog',object_xml=text)
    return r


class FullCatalogCreationTests(unittest.TestCase):
    def test_new_catalog_can_assign_its_new_forms_to_all_roles(self):
        r=forms_request();root=E.fromstring(r['object_xml']);props=root[0].find(catalog.Q+'Properties')
        import owned_form_properties,configuration_batch
        for name in owned_form_properties.profiles()['Catalog']['properties']:
            node=props.find(catalog.Q+name)
            if node is None:node=E.SubElement(props,catalog.Q+name)
            node.text='Catalog.XML_Catalog.Form.NewForm0'
        r['object_xml']=E.tostring(root,encoding='unicode');result=c.serialize(r)
        _,records=configuration_batch.read_packet(result['data'])
        parent=next(row for row in records if row.object_id==fixture.const.CID)
        native=s.Parser(s.inflate(parent.body).decode('utf-8-sig')).documents()[0]
        metadata=s.Parser(parent.metadata.decode('utf-8-sig')).documents()[0]
        for path in owned_form_properties.profiles()['Catalog']['properties'].values():
            self.assertEqual(s.val(owned_form_properties.at(native,path)),FIDS[0])
        self.assertEqual(s.metadata_relations(metadata[14])[FIDS[0]],0)

    def test_catalog_forms_are_created_in_one_graph_with_complete_streams(self):
        r=forms_request();result=c.serialize(r);transport=s.inflate(base64.b64decode(result['data'])[18:])
        raw,pos=s.read_record(transport,0);graph=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        storage,pos=s.read_record(transport,pos+4);s.validate_storage(storage)
        # Physical records are ordered as forms, Catalog, Configuration, Language.
        pos=12
        for index,fid in enumerate(FIDS):
            meta,pos=s.read_record(storage,pos);body,pos=s.read_record(storage,pos);external,pos=s.read_record(storage,pos)
            m=s.Parser(meta.decode('utf-8-sig')).documents()[0]
            self.assertEqual((s.val(m[1]),s.val(m[3]),s.val(m[10])),(fid,fixture.const.CID,str(index)))
            self.assertEqual(s.val(m[11][1]),fid+'.0')
            interface=form_xml.interface(s.inflate(external));self.assertEqual(s.val(interface[2]),'// Module '+str(index))
        meta,pos=s.read_record(storage,pos);body,pos=s.read_record(storage,pos);m=s.Parser(meta.decode('utf-8-sig')).documents()[0]
        self.assertEqual([s.val(v) for v in m[12][1][2:]],FIDS)
        native=s.Parser(s.inflate(body).decode('utf-8-sig')).documents()[0]
        self.assertEqual([s.val(v) for v in native[7][2:]],FIDS)
        self.assertEqual(s.val(graph[0][0]),'4')  # Configuration, Catalog, two forms.
        registrations={s.val(graph[6][i]):graph[6][i+1] for i in range(1,len(graph[6]),2)}
        self.assertEqual(s.val(registrations[fixture.const.CID][0]),'3')
        self.assertEqual({v['object_id'] for v in result['externals']},set(FIDS))
        self.assertTrue(all(v['action']==0 for v in result['externals']))

    def test_form_files_must_match_references_and_all_uuid_scopes(self):
        for mutation in ('missing','duplicate','inline_collision','repository_collision','name','interface','path'):
            r=forms_request()
            if mutation=='missing':r['forms'].pop()
            elif mutation=='duplicate':r['forms'][1]['definition_xml']=r['forms'][1]['definition_xml'].replace(FIDS[1],FIDS[0])
            elif mutation in ('inline_collision','repository_collision'):
                target=tables.AID if mutation=='inline_collision' else r['object_id']
                r['forms'][0]['definition_xml']=r['forms'][0]['definition_xml'].replace(FIDS[0],target)
            elif mutation=='name':r['forms'][0]['name']='WrongName'
            elif mutation=='interface':r['forms'][0]['form_xml']=None
            else:r['forms'][0]['form_xml']=r['forms'][0]['form_xml'].replace('Object.Code','Object.Unknown')
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):c.serialize(r)

    def test_complete_body_with_generated_root_ids(self):
        oid,name,raw,ids=metadata_object_xml.create(xml(), '8.5.1.1529', 'Catalog')
        body=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        self.assertEqual((oid,name),(fixture.const.CID,'XML_Catalog'))
        self.assertEqual(set(inline_object_xml.features(body, object_xml_profiles.layout('Catalog'))), {tables.SID, tables.AID, tables.BID})
        self.assertEqual(len(ids),17)  # 10 root types, 3 inline features, 4 section types.
        exported=E.tostring(metadata_object_xml.export(body, {}, '8.5.1.1529', 'Catalog'), encoding='unicode')
        self.assertEqual(metadata_object_xml.create(exported, '8.5.1.1529', 'Catalog')[2], raw)

    def test_creation_graph_and_metadata_include_inline_features(self):
        result=c.serialize(request(xml()));transport=s.inflate(base64.b64decode(result['data'])[18:])
        raw,pos=s.read_record(transport,0);graph=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        row=next(row for row in graph[1][1:] if s.val(row[0])==fixture.const.CID)
        expected={tables.SID,tables.AID,tables.BID}
        self.assertEqual(s.val(row[1]),'3');self.assertEqual({s.val(v) for v in row[2:]},expected)
        storage,pos=s.read_record(transport,pos+4);s.validate_storage(storage)
        meta,pos=s.read_record(storage,12);m=s.Parser(meta.decode('utf-8-sig')).documents()[0]
        self.assertEqual({s.val(v) for v in m[13][1:]},expected)

    def test_inline_uuid_collision_with_existing_repository_is_rejected(self):
        r=request(xml());root=E.fromstring(r['object_xml'])
        root[0].find(catalog.Q+'ChildObjects')[0].set('uuid',r['object_id'])
        r['object_xml']=E.tostring(root,encoding='unicode')
        with self.assertRaisesRegex(ValueError,'collides'):c.serialize(r)

    def test_duplicate_generated_uuid_and_separate_forms_are_rejected(self):
        for mutation in ('generated','form','unknown'):
            root=E.fromstring(xml());children=root[0].find(catalog.Q+'ChildObjects')
            if mutation=='generated':children[0].find(catalog.Q+'InternalInfo')[0][0].text=tables.AID
            elif mutation=='form':E.SubElement(children,catalog.Q+'Form').text='SeparateForm'
            else:E.SubElement(children,catalog.Q+'Unknown')
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):metadata_object_xml.create(E.tostring(root, encoding='unicode'), '8.5.1.1529', 'Catalog')


if __name__=='__main__':unittest.main()
