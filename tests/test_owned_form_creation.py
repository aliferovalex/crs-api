"""Owners share form membership, positions, feature maps and nested packets."""
import sys, tempfile, unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import metadata_context
import metadata_identifiers
import xml_namespaces
import object_creation_serializer as c, native_metadata as s
import owned_forms, owned_form_properties
import managed_form_operations, configuration_batch, preparation_plan
import test_object_xml_profiles as fixtures
from test_form_kinds_xml import common_xml

Q='{'+xml_namespaces.MD+'}'
FIDS=['aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeee1','aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeee2']


def add_forms(text,kind):
    root=E.fromstring(text);name=root[0].findtext(Q+'Properties/'+Q+'Name');forms=[]
    children=root[0].find(Q+'ChildObjects')
    if children is None:children=E.SubElement(root[0],Q+'ChildObjects')
    for fid,fname in zip(FIDS,('SecondForm','FirstForm')):
        E.SubElement(children,Q+'Form').text=fname
        definition=E.Element(Q+'MetaDataObject',version='2.21');obj=E.SubElement(definition,Q+'Form',uuid=fid)
        E.SubElement(E.SubElement(obj,Q+'Properties'),Q+'Name').text=fname
        forms.append(dict(name=fname,definition_xml=E.tostring(definition,encoding='unicode'),form_xml=common_xml(),module_text='// whole '+fname))
    props=root[0].find(Q+'Properties')
    for key in owned_form_properties.profiles()[kind]['properties']:
        node=props.find(Q+key)
        if node is None:node=E.SubElement(props,Q+key)
        node.text=kind+'.'+name+'.Form.SecondForm'
    return E.tostring(root,encoding='unicode'),forms


class OwnedFormCreationTests(unittest.TestCase):
    def test_complete_creation_packets_share_form_order_versions_and_streams(self):
        for kind in ('Catalog','Document','Enum','DataProcessor','Report','InformationRegister'):
            with self.subTest(kind=kind):
                request=fixtures.request(kind);text,forms=add_forms(fixtures.xml(kind),kind)
                request['object_xml']=text;request['forms']=forms
                result=c.serialize(request);graph,records=configuration_batch.read_packet(result['data'])
                owner=next(row for row in records if row.object_id==fixtures.OID)
                body=s.Parser(s.inflate(owner.body).decode('utf-8-sig')).documents()[0]
                self.assertEqual(owned_forms.positions(body,kind),{fid:index for index,fid in enumerate(FIDS)})
                metadata=s.Parser(owner.metadata.decode('utf-8-sig')).documents()[0]
                self.assertEqual([oid for oid,_ in metadata_context.children(metadata)],FIDS)
                self.assertEqual(s.metadata_relations(metadata[14])[FIDS[0]],0)
                for index,fid in enumerate(FIDS):
                    row=next(record for record in records if record.object_id==fid);m=s.Parser(row.metadata.decode('utf-8-sig')).documents()[0]
                    self.assertEqual((s.val(m[2]),s.val(m[3]),s.val(m[10])),(metadata_identifiers.class_id(kind+'Form'),fixtures.OID,str(index)))
                    interface=managed_form_operations.form_xml.interface(s.inflate(row.externals[0][1]));self.assertEqual(s.val(interface[2]),forms[index]['module_text'])
                self.assertEqual(s.val(graph[6][0]),'4')  # Root, owner and both forms.

    def test_preparation_discovers_both_forms_and_rejects_a_missing_interface(self):
        for kind in ('Document','Enum','Report','InformationRegister'):
            request=fixtures.request(kind);text,forms=add_forms(fixtures.xml(kind),kind)
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'Owner.xml';path.write_text(text,encoding='utf-8')
                for form in forms:
                    file=path.with_suffix('')/'Forms'/(form['name']+'.xml');file.parent.mkdir(parents=True,exist_ok=True);file.write_text(form['definition_xml'],encoding='utf-8')
                    ext=file.with_suffix('')/'Ext';ext.mkdir(parents=True);(ext/'Form.xml').write_text(form['form_xml'],encoding='utf-8')
                plan=preparation_plan.plan(dict(xml_path=str(path),platform='8.5.1.1529',context=request['context']))
                self.assertEqual([row['name'] for row in plan['forms']],['SecondForm','FirstForm'])
                (path.with_suffix('')/'Forms/FirstForm/Ext/Form.xml').unlink()
                with self.assertRaisesRegex(ValueError,'Missing or oversized'):preparation_plan.plan(dict(xml_path=str(path),context=request['context']))

    def test_enum_values_are_registered_as_features_on_creation(self):
        request=fixtures.request('Enum');root=E.fromstring(fixtures.xml('Enum'))
        value=E.SubElement(root[0].find(Q+'ChildObjects'),Q+'EnumValue',uuid='bbbbbbbb-cccc-4ddd-8eee-ffffffffffff')
        E.SubElement(E.SubElement(value,Q+'Properties'),Q+'Name').text='Value'
        text,forms=add_forms(E.tostring(root,encoding='unicode'),'Enum');request.update(object_xml=text,forms=forms)
        result=c.serialize(request);_,records=configuration_batch.read_packet(result['data']);owner=next(row for row in records if row.object_id==fixtures.OID)
        metadata=s.Parser(owner.metadata.decode('utf-8-sig')).documents()[0]
        self.assertEqual([s.val(key) for key in metadata[13][1:]],['bbbbbbbb-cccc-4ddd-8eee-ffffffffffff'])


if __name__=='__main__':unittest.main()
