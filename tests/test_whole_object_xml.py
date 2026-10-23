"""Whole target descriptions, identifiers and stale unchanged properties."""
import base64,copy,unittest
from xml.etree import ElementTree as E
import configuration_serializer
import xml_namespaces
import inline_attribute_xml
import metadata_object_xml
import native_metadata as s
import metadata_object_xml as catalog
import object_change_serializer
import test_catalog_attribute_serializer as attr
import test_commonmodule_change as module
import commonmodule_serializer
import test_configuration_serializer as root
import managed_form_operations
import test_catalog_form_serializer as forms


def body(result):
    if 'request_xml' in result:
        data=E.fromstring(result['request_xml']).find('{'+s.NS+'}params/{'+s.NS+'}data').text
    else:data=result['data']
    raw=s.inflate(base64.b64decode(data)[18:]);_,pos=s.read_record(raw,0);storage,_=s.read_record(raw,pos+4)
    s.validate_storage(storage);meta,pos=s.read_record(storage,12);data,pos=s.read_record(storage,pos)
    return s.Parser(meta.decode('utf-8-sig')).documents(),s.Parser(s.inflate(data).decode('utf-8-sig')).documents()


class WholeObjectTests(unittest.TestCase):
    def test_catalog_complete_properties_and_inline_attribute_list(self):
        r=attr.fixture();snapshot=base64.b64decode(r['snapshot']);_,pos=s.read_record(snapshot,12);data,_=s.read_record(snapshot,pos)
        source=s.Parser(s.inflate(data).decode('utf-8-sig')).documents()[0]
        top=metadata_object_xml.export(source, {}, r['platform'], 'Catalog');props=top[0].find(catalog.Q+'Properties')
        props.find(catalog.Q+'Comment').text='Whole Catalog'
        template=copy.deepcopy(source)
        first=body(object_change_serializer.serialize(r))[1][0][6][2]
        node=inline_attribute_xml.attribute_export(first)
        node.find(catalog.Q+'Properties/'+catalog.Q+'Type/{'+xml_namespaces.CORE+'}StringQualifiers/{'+xml_namespaces.CORE+'}Length').text='120'
        top[0].find(catalog.Q+'ChildObjects').append(node)
        r['object_xml']=E.tostring(top,encoding='unicode')
        result=object_change_serializer.serialize(r);meta,docs=body(result)
        self.assertNotIn('attribute_id',result)
        self.assertEqual(s.val(docs[0][1][9][1][4]),'Whole Catalog')
        self.assertEqual(s.val(docs[0][6][2][0][1][1][2][1][1]),'120')
        self.assertEqual({s.val(v) for v in meta[0][13][1:]},{node.get('uuid')})
        self.assertEqual(s.render(source[7]),s.render(docs[0][7]))

    def test_catalog_rejects_unknown_sections_and_changed_generated_ids(self):
        r=attr.fixture();_,pos=s.read_record(base64.b64decode(r['snapshot']),12);data,_=s.read_record(base64.b64decode(r['snapshot']),pos)
        source=s.Parser(s.inflate(data).decode('utf-8-sig')).documents()[0]
        for mutation in ('section','generated','form'):
            top=metadata_object_xml.export(source, {}, r['platform'], 'Catalog')
            if mutation=='section':E.SubElement(top[0].find(catalog.Q+'ChildObjects'),catalog.Q+'TabularSection',uuid=attr.catalog.const.CID)
            elif mutation=='generated':top[0].find('.//{'+xml_namespaces.READABLE+'}TypeId').text='11111111-1111-4111-8111-111111111111'
            else:E.SubElement(top[0].find(catalog.Q+'ChildObjects'),catalog.Q+'Form').text='Missing'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                object_change_serializer.serialize(dict(r,object_xml=E.tostring(top,encoding='unicode')))

    def test_module_whole_description_and_code(self):
        r=module.fixture();snapshot=base64.b64decode(r['snapshot']);_,pos=s.read_record(snapshot,12);data,_=s.read_record(snapshot,pos)
        old=s.Parser(s.inflate(data).decode('utf-8-sig')).documents()[0]
        top=catalog.export(old,{},r['platform'],'CommonModule')
        top[0].find(catalog.Q+'Properties/'+catalog.Q+'Comment').text='Whole Module'
        r['object_xml']=E.tostring(top,encoding='unicode')
        meta,docs=body(commonmodule_serializer.serialize_change(r))
        self.assertEqual(s.val(docs[0][1][1][4]),'Whole Module')
        self.assertEqual(s.val(docs[0][1][1][1][2]),r['object_id'])
        self.assertEqual(s.render(old[1][2:]),s.render(docs[0][1][2:]))
        top[0].set('uuid','11111111-1111-4111-8111-111111111111')
        with self.assertRaises(ValueError):commonmodule_serializer.serialize_change(dict(r,object_xml=E.tostring(top,encoding='unicode')))

    def test_root_checks_baseline_even_for_unchanged_target_property(self):
        r,_=root.property_fixture('8.5.1.1529');before=E.fromstring(r['before_xml']);after=E.fromstring(r['after_xml'])
        before.find('.//Vendor').text='Stale';after.find('.//Vendor').text='Stale'
        after.find('.//Comment').text='Changed'
        r.update(before_xml=E.tostring(before,encoding='unicode'),after_xml=E.tostring(after,encoding='unicode'))
        with self.assertRaisesRegex(ValueError,'Baseline XML Vendor'):configuration_serializer.serialize(r)

    def test_form_definition_from_complete_xml_preserves_uuid_and_properties(self):
        r=forms.fixture();oid='44444444-4444-4444-8444-444444444444'
        top=E.Element(catalog.Q+'MetaDataObject',version='2.21');obj=E.SubElement(top,catalog.Q+'Form',uuid=oid)
        props=E.SubElement(obj,catalog.Q+'Properties')
        E.SubElement(props,catalog.Q+'Name').text=r['name']
        E.SubElement(props,catalog.Q+'Synonym');E.SubElement(props,catalog.Q+'Comment').text='Whole Form Definition'
        E.SubElement(props,catalog.Q+'FormType').text='Managed'
        r['definition_xml']=E.tostring(top,encoding='unicode')
        result=managed_form_operations.create(r);meta,docs=body(result)
        self.assertEqual(result['object_id'],oid)
        common=docs[0][1][1][1];self.assertEqual(s.val(common[4]),'Whole Form Definition')
        self.assertEqual(s.val(common[1][2]),oid)
        props.find(catalog.Q+'FormType').text='Ordinary'
        with self.assertRaises(ValueError):managed_form_operations.create(dict(r,definition_xml=E.tostring(top,encoding='unicode')))


if __name__=='__main__':unittest.main()
