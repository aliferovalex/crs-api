"""Table column appearance rebuilt from complete XML and native CF samples."""
import hashlib,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/Сериализация'))
import metadata_serializer as s,managed_form_xml as x,managed_form_elements as elements,v8unpack_backend as b


class ColumnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=Path(__file__).with_name('fixtures');cls.fixture=json.loads((folder/'form_column_rules_851.json').read_text(encoding='utf-8'));base=json.loads((folder/'form_rules_851.json').read_text(encoding='utf-8'))
        cls.paths=x.ObjectPaths({k:s.Parser(v).documents()[0] for k,v in base['paths'].items()});cls.paths.types=base['types'];cls.paths.tables=set(base['tables'])

    def convert(self,kind,xml,source=None):
        return x.convert(source or self.fixture['bases'][kind].encode('utf-8'),xml,paths=self.paths,object_name='CRSAPI_FullCatalog')

    def test_complete_interfaces_match_63_native_samples(self):
        self.assertEqual(len(self.fixture['cases']),63)
        for case in self.fixture['cases']:
            with self.subTest(kind=case['kind'],name=case['name'],value=case['value']):
                result=self.convert(case['kind'],case['xml']);signature=b.signature(s.Parser(result.decode('utf-8-sig')).documents())
                self.assertEqual(hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest(),case['sha256'])

    def test_full_xml_property_removal_restores_column_defaults(self):
        case=next(c for c in self.fixture['cases'] if c['kind']=='InputField' and c['name']=='FooterText')
        root=E.fromstring(case['xml']);field=root.find('.//'+x.Q+'InputField');E.SubElement(field,x.Q+'ShowInFooter').text='true';E.SubElement(field,x.Q+'AutoCellHeight').text='false'
        first=self.convert(case['kind'],E.tostring(root,encoding='unicode'))
        for name in ('FooterText','ShowInFooter','AutoCellHeight'):field.remove(field.find(x.Q+name))
        restored=self.convert(case['kind'],E.tostring(root,encoding='unicode'),first)
        self.assertEqual(b.signature(x.interface(restored)),b.signature(x.interface(self.fixture['bases']['InputField'].encode('utf-8'))))

    def test_column_move_reorder_and_removal_keep_appearance(self):
        case=next(c for c in self.fixture['cases'] if c['kind']=='LabelField' and c['name']=='FooterText');root=E.fromstring(case['xml']);table=root.find(x.Q+'ChildItems')[0];fields=table.find(x.Q+'ChildItems');label=fields[0]
        check=E.SubElement(fields,x.Q+'CheckBoxField',name='ActiveColumn',id='120');E.SubElement(check,x.Q+'DataPath').text='Object.Rows.Active';E.SubElement(check,x.Q+'ShowInFooter').text='true';E.SubElement(check,x.Q+'FooterHorizontalAlign').text='Center'
        first=self.convert('LabelField',E.tostring(root,encoding='unicode'));fields[:]=[check,label]
        second=self.convert('LabelField',E.tostring(root,encoding='unicode'),first);form=x.interface(second);index,_,_=elements.form_collection(form);entry=form[1][index+2];child=elements.table_children(entry)
        self.assertEqual(s.val(entry[child]),'2');self.assertEqual(s.val(entry[child+2][6]),'ActiveColumn');self.assertEqual(s.val(entry[child+2][21]),'1')
        self.assertEqual(s.val(entry[child+4][19][2][1]),'Footer text')
        fields.remove(check);third=self.convert('LabelField',E.tostring(root,encoding='unicode'),second);self.assertNotIn('ActiveColumn',b.form_model(x.interface(third))['elements']['data'])

    def test_ignored_native_names_and_unknown_alignments_are_rejected(self):
        case=next(c for c in self.fixture['cases'] if c['kind']=='InputField' and c['name']=='baseline')
        for name,value in [('HeaderFont',None),('HeaderVerticalAlign','Top'),('FooterHorizontalAlign','Unexpected')]:
            root=E.fromstring(case['xml']);field=root.find('.//'+x.Q+'InputField');node=E.SubElement(field,x.Q+name);node.text=value
            with self.subTest(name=name),self.assertRaises(ValueError):self.convert('InputField',E.tostring(root,encoding='unicode'))


if __name__=='__main__':unittest.main()
