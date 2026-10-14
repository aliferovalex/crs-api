"""Verified scalar type patterns, whole Attribute XML and Constant packets."""
import base64,copy,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import metadata_serializer as s,type_description_xml as types,catalog_object_xml as catalog,constant_serializer as c
import catalog_change_serializer as attributes
import test_catalog_attribute_serializer as attr
import test_constant_serializer as constants

PATTERNS=['{"Pattern",{"S",64,1}}','{"Pattern",{"N",15,2,0}}','{"Pattern",{"N",10,0,1}}','{"Pattern",{"B"}}','{"Pattern",{"D"}}','{"Pattern",{"D","D"}}','{"Pattern",{"D","T"}}']


class ScalarTypeTests(unittest.TestCase):
    def test_all_supported_patterns_roundtrip(self):
        for value in PATTERNS:
            pattern=s.Parser(value).documents()[0]
            with self.subTest(value=value):self.assertEqual(s.render(types.read(types.export(pattern,catalog.Q+'Type'))),value)

    def test_invalid_qualifiers_composites_and_reference_types(self):
        pattern=s.Parser(PATTERNS[1]).documents()[0]
        base=types.export(pattern,catalog.Q+'Type')
        for name,value in [('Digits','39'),('Digits','0'),('FractionDigits','16'),('FractionDigits','-1'),('AllowedSign','Other')]:
            target=copy.deepcopy(base);target[1].find(types.Q+name).text=value
            with self.subTest(name=name,value=value),self.assertRaises(ValueError):types.read(target)
        for type_name in ('cfg:CatalogRef.Items','xs:integer'):
            target=copy.deepcopy(base);target[0].text=type_name
            with self.assertRaises(ValueError):types.read(target)
        target=copy.deepcopy(base);target.append(copy.deepcopy(target[0]))
        with self.assertRaises(ValueError):types.read(target)

    def test_whole_catalog_with_all_scalar_attributes_and_type_changes(self):
        r=attr.fixture();store=base64.b64decode(r['snapshot']);_,pos=s.read_record(store,12);data,_=s.read_record(store,pos)
        source=s.Parser(s.inflate(data).decode('utf-8-sig')).documents()[0];top=catalog.export(source,{},r['platform'])
        children=top[0].find(catalog.Q+'ChildObjects')
        for i,value in enumerate(PATTERNS):
            node=E.SubElement(children,catalog.Q+'Attribute',uuid='33333333-3333-4333-8333-%012d'%i);props=E.SubElement(node,catalog.Q+'Properties')
            E.SubElement(props,catalog.Q+'Name').text='Typed'+str(i);props.append(types.export(s.Parser(value).documents()[0],catalog.Q+'Type'))
        r.pop('name');r.pop('length');r['object_xml']=E.tostring(top,encoding='unicode')
        result=attributes.serialize(r);payload=E.fromstring(result['request_xml']).find('{'+s.NS+'}params/{'+s.NS+'}data').text
        transport=s.inflate(base64.b64decode(payload)[18:]);_,pos=s.read_record(transport,0);store,_=s.read_record(transport,pos+4)
        meta,pos=s.read_record(store,12);data,_=s.read_record(store,pos);body=s.Parser(s.inflate(data).decode('utf-8-sig')).documents()[0]
        self.assertEqual([s.render(v[0][1][1][2]) for v in body[6][2:]],PATTERNS)
        self.assertEqual(s.val(s.Parser(meta.decode('utf-8-sig')).documents()[0][13][0]),str(len(PATTERNS)))
        for entry in body[6][2:]:
            node=catalog.attribute_export(entry);_,_,rebuilt=catalog.attribute_xml(node)
            self.assertEqual(s.render(entry),s.render(rebuilt))
        # Same UUID, different type: target XML is authoritative.
        first=children[0].find(catalog.Q+'Properties');first.remove(first.find(catalog.Q+'Type'));first.append(types.export(s.Parser(PATTERNS[1]).documents()[0],catalog.Q+'Type'))
        raw,_=catalog.convert(E.tostring(top,encoding='unicode'),r['platform'],body,{})
        changed=s.Parser(raw.decode('utf-8-sig')).documents()[0][6][2]
        self.assertEqual(s.render(changed[0][1][1][2]),PATTERNS[1])

    def test_scalar_constants_use_same_reader(self):
        for value in PATTERNS[1:]:
            r=constants.fixture('8.5.1.1529');top=E.fromstring(r['constant_xml']);props=top[0].find(catalog.Q+'Properties')
            props.remove(props.find(catalog.Q+'Type'));props.append(types.export(s.Parser(value).documents()[0],catalog.Q+'Type'))
            r['constant_xml']=E.tostring(top,encoding='unicode')
            with self.subTest(value=value):
                result=c.serialize(r);self.assertEqual(result['object_id'],constants.CID)
            with self.assertRaisesRegex(ValueError,'legacy profile'):c.constant_xml(r['constant_xml'],'8.5.4.1878')


if __name__=='__main__':unittest.main()
