"""Full interfaces for format strings, input masks and formatted titles."""
import hashlib,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/Сериализация'))
import metadata_serializer as s,managed_form_xml as x,v8unpack_backend as b,rich_text_xml as rich


class TextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=Path(__file__).with_name('fixtures');cls.fixture=json.loads((folder/'form_text_rules_851.json').read_text(encoding='utf-8'));cls.base=json.loads((folder/'form_rules_851.json').read_text(encoding='utf-8'))
        cls.paths=x.ObjectPaths({k:s.Parser(v).documents()[0] for k,v in cls.base['paths'].items()});cls.paths.types=cls.base['types'];cls.paths.tables=set(cls.base['tables'])

    def convert(self,case,xml=None,source=None):
        return x.convert(source or self.base['bases'][case['kind']].encode('utf-8'),xml or case['xml'],paths=self.paths,object_name='CRSAPI_FullCatalog')

    def test_full_interfaces_match_60_native_samples(self):
        self.assertEqual(len(self.fixture['cases']),60)
        for case in self.fixture['cases']:
            with self.subTest(kind=case['kind'],name=case['name'],value=case['value']):
                signature=b.signature(s.Parser(self.convert(case).decode('utf-8-sig')).documents())
                self.assertEqual(hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest(),case['sha256'])

    def test_projection_preserves_native_escape_image_and_unclosed_rules(self):
        self.assertEqual(rich.plain_text('<<b>X</>'),'<'+'b>X')
        self.assertEqual(rich.plain_text('X <img StdPicture.Refresh> Y'),'X   Y')
        self.assertEqual(rich.plain_text('<IMG StdPicture.Refresh>'),'')
        self.assertEqual(rich.plain_text('Text <unfinished'),'Text ')
        self.assertEqual(rich.plain_text('A &amp; B &lt; C'),'A &amp; B &lt; C')

    def test_rich_to_plain_and_title_removal_rebuild_both_values(self):
        case=next(c for c in self.fixture['cases'] if c['kind']=='LabelDecoration' and '<b>Nested' in c['value'])
        root=E.fromstring(case['xml']);node=root.find('.//'+x.Q+'Title');first=self.convert(case)
        node.set('formatted','false');second=self.convert(case,E.tostring(root,encoding='unicode'),first)
        self.assertIn('<b>Nested',s.render(x.interface(second)))
        root.find('.//'+x.Q+'LabelDecoration').remove(node);restored=self.convert(case,E.tostring(root,encoding='unicode'),second)
        self.assertEqual(b.signature(x.interface(restored)),b.signature(x.interface(self.base['bases']['LabelDecoration'].encode('utf-8'))))

    def test_format_and_mask_removal_restore_inherited_values(self):
        case=next(c for c in self.fixture['cases'] if c['kind']=='InputField' and c['name']=='Format');root=E.fromstring(case['xml']);field=root.find('.//'+x.Q+'InputField');E.SubElement(field,x.Q+'Mask').text='999-999'
        first=self.convert(case,E.tostring(root,encoding='unicode'));field.remove(field.find(x.Q+'Format'));field.remove(field.find(x.Q+'Mask'))
        restored=self.convert(case,E.tostring(root,encoding='unicode'),first)
        self.assertEqual(b.signature(x.interface(restored)),b.signature(x.interface(self.base['bases']['InputField'].encode('utf-8'))))

    def test_invalid_attributes_and_non_scalar_mask_are_rejected(self):
        case=next(c for c in self.fixture['cases'] if c['kind']=='InputField' and c['name']=='Mask');root=E.fromstring(case['xml']);E.SubElement(root.find('.//'+x.Q+'Mask'),x.Q+'Extra')
        with self.assertRaises(ValueError):self.convert(case,E.tostring(root,encoding='unicode'))
        case=next(c for c in self.fixture['cases'] if c['kind']=='LabelDecoration' and c['name']=='Title');root=E.fromstring(case['xml']);root.find('.//'+x.Q+'Title').set('formatted','yes')
        with self.assertRaises(ValueError):self.convert(case,E.tostring(root,encoding='unicode'))


if __name__=='__main__':unittest.main()
