"""Border styles, references and whole interfaces matched to native exports."""
import hashlib,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/Сериализация'))
import metadata_serializer as s,managed_form_xml as x,appearance_xml as a,v8unpack_backend as b

UI='http://v8.1c.ru/8.1/data/ui'
XSI='{http://www.w3.org/2001/XMLSchema-instance}'


def border(style=None,width=None):
    node=E.Element('Border')
    if width is not None:node.set('width',width)
    if style is not None:child=E.SubElement(node,'{'+UI+'}style');child.set(XSI+'type','ui:ControlBorderType');child.text=style
    return node


class BorderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=Path(__file__).with_name('fixtures');cls.fixture=json.loads((folder/'form_border_rules_851.json').read_text(encoding='utf-8'));cls.base=json.loads((folder/'form_rules_851.json').read_text(encoding='utf-8'))
        cls.paths=x.ObjectPaths({k:s.Parser(v).documents()[0] for k,v in cls.base['paths'].items()});cls.paths.types=cls.base['types'];cls.paths.tables=set(cls.base['tables'])

    def convert(self,case,xml=None,source=None):
        return x.convert(source or self.base['bases'][case['kind']].encode('utf-8'),xml or case['xml'],paths=self.paths,object_name='CRSAPI_FullCatalog')

    def test_whole_interfaces_match_56_native_samples(self):
        self.assertEqual(len(self.fixture['cases']),56)
        for case in self.fixture['cases']:
            with self.subTest(kind=case['kind'],name=case['name'],value=case['value']):
                signature=b.signature(s.Parser(self.convert(case).decode('utf-8-sig')).documents())
                self.assertEqual(hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest(),case['sha256'])

    def test_style_codes_width_and_empty_border_are_distinct(self):
        bindings={'ui':UI}
        self.assertEqual(s.render(a.border(border('Double','5'),bindings)),'{3,0,{0},200,5,0,48312c09-257f-4b29-b280-284dd89efc1e}')
        self.assertEqual(s.render(a.border(border(None,'3'),bindings)),'{3,0,{0},0,3,0,00000000-0000-0000-0000-000000000000}')
        self.assertEqual(s.render(a.border(border(),bindings)),'{3,0,{0},0,0,0,00000000-0000-0000-0000-000000000000}')

    def test_style_reference_namespace_alias_and_width_override(self):
        node=E.Element('Border',ref='theme:ControlBorder',width='2')
        self.assertEqual(s.render(a.border(node,{'theme':'http://v8.1c.ru/8.1/data/ui/style'})),'{3,1,{-18},0,2,0}')
        with self.assertRaises(ValueError):a.border(node,{'theme':'http://example.org/unverified'})

    def test_complete_xml_removal_restores_inherited_border_and_color(self):
        case=next(c for c in self.fixture['cases'] if c['kind']=='LabelDecoration' and c['name']=='Border' and c['value']=={'width':'5','style':'Single'})
        root=E.fromstring(case['xml']);field=root.find(x.Q+'ChildItems')[0];E.SubElement(field,x.Q+'BorderColor').text='#112233'
        xml=E.tostring(root,encoding='unicode').replace('version="2.21"','version="2.21" xmlns:v8ui="'+UI+'"')
        changed=self.convert(case,xml)
        field.remove(field.find(x.Q+'Border'));field.remove(field.find(x.Q+'BorderColor'))
        restored=self.convert(case,E.tostring(root,encoding='unicode'),changed)
        self.assertEqual(b.signature(x.interface(restored)),b.signature(x.interface(self.base['bases']['LabelDecoration'].encode('utf-8'))))

    def test_invalid_styles_types_and_widths_are_rejected(self):
        for value in ('-1','1.5','1000000'):
            with self.subTest(width=value),self.assertRaises(ValueError):a.border(border('Single',value),{'ui':UI})
        with self.assertRaisesRegex(ValueError,'style'):a.border(border('Unverified','1'),{'ui':UI})
        with self.assertRaisesRegex(ValueError,'type'):a.border(border('Single','1'),{'ui':'http://example.org/unverified'})
        node=border('Single','1');node.set('ref','theme:ControlBorder')
        with self.assertRaisesRegex(ValueError,'explicit style'):a.border(node,{'ui':UI,'theme':'http://v8.1c.ru/8.1/data/ui/style'})


if __name__=='__main__':unittest.main()
