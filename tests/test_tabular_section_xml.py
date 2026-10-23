"""Complete tabular XML, nested scalar attributes and repository feature maps."""
import base64, sys, unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import metadata_object_xml
import native_metadata as s, metadata_object_xml as c, tabular_section_xml as t, type_description_xml as types
import object_change_serializer as serializer
import test_catalog_attribute_serializer as fixture

SID='44444444-4444-4444-8444-444444444444';AID='55555555-5555-4555-8555-555555555555';BID='66666666-6666-4666-8666-666666666666'


def section(name='Rows',sid=SID):
    node=E.Element(c.Q+'TabularSection',uuid=sid);internal=E.SubElement(node,c.Q+'InternalInfo')
    for i,(prefix,category) in enumerate([('CatalogTabularSection.','TabularSection'),('CatalogTabularSectionRow.','TabularSectionRow')]):
        generated=E.SubElement(internal,t.XR+'GeneratedType',name=prefix+'XML_Catalog.'+name,category=category)
        E.SubElement(generated,t.XR+'TypeId').text='77777777-7777-4777-8777-%012d'%(i*2)
        E.SubElement(generated,t.XR+'ValueId').text='77777777-7777-4777-8777-%012d'%(i*2+1)
    props=E.SubElement(node,c.Q+'Properties');E.SubElement(props,c.Q+'Name').text=name
    children=E.SubElement(node,c.Q+'ChildObjects')
    for aid,aname,pattern in [(AID,'Text','{"Pattern",{"S",80,1}}'),(BID,'Quantity','{"Pattern",{"N",15,3,1}}')]:
        attr=E.SubElement(children,c.Q+'Attribute',uuid=aid);p=E.SubElement(attr,c.Q+'Properties');E.SubElement(p,c.Q+'Name').text=aname
        p.append(types.export(s.Parser(pattern).documents()[0],c.Q+'Type'))
    return node


def source():
    r=fixture.fixture();data=base64.b64decode(r['snapshot']);_,pos=s.read_record(data,12);body,_=s.read_record(data,pos)
    return r,s.Parser(s.inflate(body).decode('utf-8-sig')).documents()[0]


class TabularTests(unittest.TestCase):
    def test_creation_full_export_and_feature_map(self):
        r,body=source();top=metadata_object_xml.export(body, {}, r['platform'], 'Catalog');top[0].find(c.Q+'ChildObjects').append(section())
        r['object_xml']=E.tostring(top,encoding='unicode')
        result=serializer.serialize(r);data=E.fromstring(result['request_xml']).find('{'+s.NS+'}params/{'+s.NS+'}data').text
        transport=s.inflate(base64.b64decode(data)[18:]);_,pos=s.read_record(transport,0);snapshot,_=s.read_record(transport,pos+4)
        meta,pos=s.read_record(snapshot,12);bodydata,_=s.read_record(snapshot,pos);new=s.Parser(s.inflate(bodydata).decode('utf-8-sig')).documents()[0]
        self.assertEqual({s.val(v) for v in s.Parser(meta.decode('utf-8-sig')).documents()[0][13][1:]},{SID,AID,BID})
        self.assertEqual(s.val(new[5][1]),'1');self.assertEqual(s.val(t.common(new[5][2])[2]),'Rows')
        self.assertEqual(s.val(t.attributes(new[5][2])[1][0][1][1][2][1][2]),'3')
        exported=metadata_object_xml.export(new, {}, r['platform'], 'Catalog');raw,features=metadata_object_xml.change(E.tostring(exported, encoding='unicode'), r['platform'], 'Catalog', new, {})
        self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()[0]),s.render(new));self.assertEqual(set(features),{SID,AID,BID})

    def test_changes_and_deletion_use_complete_child_list(self):
        r,body=source();top=metadata_object_xml.export(body, {}, r['platform'], 'Catalog');top[0].find(c.Q+'ChildObjects').append(section())
        raw,_=metadata_object_xml.change(E.tostring(top, encoding='unicode'), r['platform'], 'Catalog', body, {})
        old=s.Parser(raw.decode('utf-8-sig')).documents()[0];target=metadata_object_xml.export(old, {}, r['platform'], 'Catalog')
        sec=target[0].find(c.Q+'ChildObjects/'+c.Q+'TabularSection');columns=sec.find(c.Q+'ChildObjects');columns.remove(columns[0])
        columns[0].find(c.Q+'Properties/'+c.Q+'Type/'+types.Q+'NumberQualifiers/'+types.Q+'FractionDigits').text='4'
        raw,features=metadata_object_xml.change(E.tostring(target, encoding='unicode'), r['platform'], 'Catalog', old, {})
        new=s.Parser(raw.decode('utf-8-sig')).documents()[0];self.assertEqual(set(features),{SID,BID})
        self.assertEqual(s.val(t.attributes(new[5][2])[0][0][1][1][2][1][2]),'4')
        target[0].find(c.Q+'ChildObjects').remove(sec);raw,features=metadata_object_xml.change(E.tostring(target, encoding='unicode'), r['platform'], 'Catalog', old, {})
        self.assertEqual(features,[]);self.assertEqual(s.val(s.Parser(raw.decode('utf-8-sig')).documents()[0][5][1]),'0')

    def test_rejects_duplicate_ids_unknown_properties_and_generated_id_changes(self):
        r,body=source();top=metadata_object_xml.export(body, {}, r['platform'], 'Catalog');top[0].find(c.Q+'ChildObjects').append(section())
        raw,_=metadata_object_xml.change(E.tostring(top, encoding='unicode'), r['platform'], 'Catalog', body, {})
        old=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        for mutation in ('duplicate','generated','property','scope'):
            target=metadata_object_xml.export(old, {}, r['platform'], 'Catalog');sec=target[0].find(c.Q+'ChildObjects/'+c.Q+'TabularSection')
            if mutation=='duplicate':sec.find(c.Q+'ChildObjects')[0].set('uuid',SID)
            elif mutation=='generated':sec.find(c.Q+'InternalInfo')[0][0].text='88888888-8888-4888-8888-888888888888'
            elif mutation=='property':E.SubElement(sec.find(c.Q+'Properties'),c.Q+'Unknown').text='x'
            else:
                column=sec.find(c.Q+'ChildObjects')[0];sec.find(c.Q+'ChildObjects').remove(column);target[0].find(c.Q+'ChildObjects').append(column)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):metadata_object_xml.change(E.tostring(target, encoding='unicode'), r['platform'], 'Catalog', old, {})

    def test_low_level_removal_preserves_forms_for_final_stream_validation(self):
        r,body=source();top=metadata_object_xml.export(body, {}, r['platform'], 'Catalog');top[0].find(c.Q+'ChildObjects').append(section())
        raw,_=metadata_object_xml.change(E.tostring(top, encoding='unicode'), r['platform'], 'Catalog', body, {})
        old=s.Parser(raw.decode('utf-8-sig')).documents()[0];fid='99999999-9999-4999-8999-999999999999'
        old[7]=[old[7][0],s.atom(1),s.atom(fid)];forms={'Form':fid}
        target=metadata_object_xml.export(old, forms, r['platform'], 'Catalog');sec=target[0].find(c.Q+'ChildObjects/'+c.Q+'TabularSection');columns=sec.find(c.Q+'ChildObjects');columns.remove(columns[0])
        raw,features=metadata_object_xml.change(E.tostring(target, encoding='unicode'), r['platform'], 'Catalog', old, forms)
        actual=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        self.assertNotIn(AID,features);self.assertIn(BID,features)
        self.assertEqual(s.render(actual[7]),s.render(old[7]))


if __name__=='__main__':unittest.main()
