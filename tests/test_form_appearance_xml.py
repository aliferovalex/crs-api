"""Compound codecs and complete interfaces checked against native CF samples."""
import hashlib,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/Сериализация'))
import native_metadata as s, managed_form_xml as x, appearance_xml as a, v8unpack_backend as b


class AppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=Path(__file__).with_name('fixtures');cls.fixture=json.loads((folder/'form_appearance_rules_851.json').read_text(encoding='utf-8'));cls.base=json.loads((folder/'form_rules_851.json').read_text(encoding='utf-8'))
        cls.paths=x.ObjectPaths({k:s.Parser(v).documents()[0] for k,v in cls.base['paths'].items()});cls.paths.types=cls.base['types'];cls.paths.tables=set(cls.base['tables'])

    def convert(self,case,xml=None,source=None):
        return x.convert(source or self.base['bases'][case['kind']].encode('utf-8'),xml or case['xml'],paths=self.paths,object_name='CRSAPI_FullCatalog')

    def test_whole_interfaces_match_independent_native_samples(self):
        self.assertGreater(len(self.fixture['cases']),90)
        for case in self.fixture['cases']:
            with self.subTest(kind=case['kind'],name=case['name'],value=case['value']):
                signature=b.signature(s.Parser(self.convert(case).decode('utf-8-sig')).documents())
                self.assertEqual(hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest(),case['sha256'])

    def test_rgb_is_general_and_references_use_namespace_uri(self):
        node=E.Element('TextColor');node.text='#010203'
        self.assertEqual(s.render(a.color(node,{})),'{4,0,{197121},0}')
        node.text='#ffffff';self.assertEqual(s.render(a.color(node,{})),'{4,0,{16777215},0}')
        node.text='palette:Red';self.assertEqual(s.render(a.color(node,{'palette':'http://v8.1c.ru/8.1/data/ui/colors/web'})),'{4,2,{119},2}')
        with self.assertRaises(ValueError):a.color(node,{'palette':'http://example.org/unverified'})

    def test_combined_font_flags_and_fractional_height(self):
        node=E.Element('Font',kind='StyleItem',ref='style:NormalTextFont',height='14.5',bold='false',italic='true',underline='false',strikeout='true')
        bindings={'style':'http://v8.1c.ru/8.1/data/ui/style'}
        self.assertEqual(s.render(a.font(node,bindings)),'{8,2,62,{-31},145,400,1,0,1,1,100}')
        node.attrib.pop('ref');node.set('kind','Absolute');node.set('faceName','Times New Roman')
        self.assertEqual(s.render(a.font(node,bindings)),'{8,0,63,145,0,0,0,400,1,0,1,0,0,0,0,0,"Times New Roman",1,100,0}')

    def test_full_xml_namespace_alias_and_property_removal(self):
        case=next(c for c in self.fixture['cases'] if c['kind']=='InputField' and c['name']=='TextColor' and c['value']=='web:Red')
        xml=case['xml'].replace('xmlns:web=','xmlns:palette=').replace('web:Red','palette:Red');self.assertEqual(b.signature(x.interface(self.convert(case,xml))),b.signature(x.interface(self.convert(case))))
        root=E.fromstring(xml);field=root.find(x.Q+'ChildItems')[0];E.SubElement(field,x.Q+'Font',kind='Absolute',faceName='Arial',height='12',bold='true')
        first=self.convert(case,E.tostring(root,encoding='unicode').replace('version="2.21"','version="2.21" xmlns:palette="http://v8.1c.ru/8.1/data/ui/colors/web"'))
        field.remove(field.find(x.Q+'TextColor'));field.remove(field.find(x.Q+'Font'))
        restored=self.convert(case,E.tostring(root,encoding='unicode'),first)
        self.assertEqual(b.signature(x.interface(restored)),b.signature(x.interface(self.base['bases']['InputField'].encode('utf-8'))))

    def test_invalid_values_are_rejected(self):
        for text in ('#12345','#12345678','web:Unverified',''):
            node=E.Element('Color');node.text=text
            with self.subTest(color=text),self.assertRaises(ValueError):a.color(node,{'web':'http://v8.1c.ru/8.1/data/ui/colors/web'})
        for attrs in ({'kind':'Absolute','faceName':'Arial','height':'9.55'},{'kind':'Absolute','faceName':'Arial','bold':'yes'},{'kind':'Absolute','faceName':'Arial','unknown':'value'},{'kind':'StyleItem','ref':'style:Unverified'}):
            with self.subTest(font=attrs),self.assertRaises(ValueError):a.font(E.Element('Font',attrs),{'style':'http://v8.1c.ru/8.1/data/ui/style'})


if __name__=='__main__':unittest.main()
