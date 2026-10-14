"""Whole interfaces compared with independent native 8.5.1 CF exports."""
import hashlib,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/Сериализация'))
import metadata_serializer as s,managed_form_xml as x,managed_form_elements as e
import managed_form_rules as rules,v8unpack_backend as b


class RulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=json.loads(Path(__file__).with_name('fixtures').joinpath('form_rules_851.json').read_text(encoding='utf-8'))
        cls.paths=x.ObjectPaths({k:s.Parser(v).documents()[0] for k,v in cls.fixture['paths'].items()})
        cls.paths.types=cls.fixture['types'];cls.paths.tables=set(cls.fixture['tables'])

    def test_complete_interfaces_match_157_native_samples(self):
        self.assertEqual(len(self.fixture['cases']),157)
        for case in self.fixture['cases']:
            with self.subTest(kind=case['kind'],name=case['name']):
                source=self.fixture['bases']['InputField' if case['kind']=='Form' else case['kind']].encode('utf-8')
                result=x.convert(source,case['xml'],paths=self.paths,object_name='CRSAPI_FullCatalog')
                signature=b.signature(s.Parser(result.decode('utf-8-sig')).documents())
                self.assertEqual(hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest(),case['sha256'])

    def test_events_sort_and_group_bindings_and_flags(self):
        node=E.Element(e.Q+'Events')
        for name in ('OnOpen','AfterWrite','BeforeClose'):E.SubElement(node,e.Q+'Event',name=name).text='Handle'+name
        result=e.events(node,'Form',s.Parser('{0,1,0}').documents()[0]);allowed=rules.event_names('Form')
        ordered=sorted((allowed[c.get('name')],c.text) for c in node)
        self.assertEqual(len(result),18)
        self.assertEqual([s.val(v) for v in result[1:7]],[v for pair in ordered for v in pair])
        self.assertEqual([s.val(v) for v in result[7:]],['1','0']+[v for guid,_ in ordered for v in (guid,'0','1')])
        self.assertEqual(s.render(e.events(None,'Form',result)),'{0,1,0}')

    def test_omitted_properties_and_events_reset_whole_control(self):
        sample=next(c for c in self.fixture['cases'] if c['kind']=='InputField' and c['name']=='events')
        source=self.fixture['bases']['InputField'].encode('utf-8');root=E.fromstring(sample['xml']);field=root.find(x.Q+'ChildItems')[0]
        E.SubElement(field,x.Q+'Width').text='29';E.SubElement(field,x.Q+'PasswordMode').text='true'
        changed=x.convert(source,E.tostring(root,encoding='unicode'),paths=self.paths,object_name='CRSAPI_FullCatalog')
        for name in ('Events','Width','PasswordMode'):field.remove(field.find(x.Q+name))
        restored=x.convert(changed,E.tostring(root,encoding='unicode'),paths=self.paths,object_name='CRSAPI_FullCatalog')
        _,_,raw_index=e.form_collection(x.interface(restored));entry=x.interface(restored)[1][raw_index-1]
        self.assertEqual(s.val(entry[39][2]),'0');self.assertEqual(s.val(entry[39][7]),'2')
        self.assertEqual(s.render(entry[39][36]),'{0,1,0}');self.assertEqual(s.render(entry[40]),'{0,1,0}')

    def test_ignored_native_names_and_invalid_sizes_are_rejected(self):
        source=self.fixture['bases']['InputField'].encode('utf-8')
        sample=next(c for c in self.fixture['cases'] if c['kind']=='InputField' and c['name']=='Width')
        for value in ('-1','1.5','true','9999999'):
            root=E.fromstring(sample['xml']);root.find('.//'+x.Q+'Width').text=value
            with self.subTest(value=value),self.assertRaises(ValueError):x.convert(source,E.tostring(root,encoding='unicode'),paths=self.paths,object_name='CRSAPI_FullCatalog')
        root=E.fromstring(sample['xml']);node=E.SubElement(root.find(x.Q+'ChildItems')[0],x.Q+'Events');E.SubElement(node,x.Q+'Event',name='Drop').text='DropHandler'
        with self.assertRaisesRegex(ValueError,'event'):x.convert(source,E.tostring(root,encoding='unicode'),paths=self.paths,object_name='CRSAPI_FullCatalog')

    def test_table_event_header_and_tail_follow_column_changes(self):
        from test_managed_form_table import xml,convert
        root=xml();table=root.find(x.Q+'ChildItems')[0]
        node=E.SubElement(table,x.Q+'Events')
        for name in ('DragCheck','OnChange'):E.SubElement(node,x.Q+'Event',name=name).text='Handle'+name
        E.SubElement(table,x.Q+'AutoMaxWidth').text='false'
        first=convert(root)
        columns=table.find(x.Q+'ChildItems');columns.remove(columns[0]);second=convert(root,first)
        for raw,count in ((first,2),(second,1)):
            form=x.interface(raw);index,_,_=e.form_collection(form);entry=form[1][index+2]
            child=e.table_children(entry)
            self.assertEqual(s.val(entry[child]),str(count))
            self.assertEqual(s.val(entry[child-6][0]),'2')
            self.assertEqual(s.val(entry[child+1+2*count+22]),'0')
        table.remove(node);third=convert(root,second);form=x.interface(third);index,_,_=e.form_collection(form);entry=form[1][index+2]
        self.assertEqual(s.render(entry[e.table_children(entry)-6]),'{0,1,0}')

    def test_enum_interfaces_match_native_exports(self):
        fixture=json.loads(Path(__file__).with_name('fixtures').joinpath('form_enum_rules_851.json').read_text(encoding='utf-8'))
        self.assertGreater(len(fixture['cases']),100)
        for case in fixture['cases']:
            with self.subTest(kind=case['kind'],property=case['name'],value=case['value']):
                source=self.fixture['bases'][case['kind']].encode('utf-8')
                result=x.convert(source,case['xml'],paths=self.paths,object_name='CRSAPI_FullCatalog')
                signature=b.signature(s.Parser(result.decode('utf-8-sig')).documents())
                self.assertEqual(hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest(),case['sha256'])

    def test_enum_change_removal_and_unknown_value(self):
        sample=next(c for c in self.fixture['cases'] if c['kind']=='InputField' and c['name']=='Width')
        root=E.fromstring(sample['xml']);field=root.find(x.Q+'ChildItems')[0];node=E.SubElement(field,x.Q+'TitleLocation');node.text='Top'
        source=self.fixture['bases']['InputField'].encode('utf-8')
        changed=x.convert(source,E.tostring(root,encoding='unicode'),paths=self.paths,object_name='CRSAPI_FullCatalog')
        form=x.interface(changed);index,_,_=e.form_collection(form)
        self.assertEqual(s.val(form[1][index+2][7]),'3')
        node.text='Unexpected'
        with self.assertRaisesRegex(ValueError,'TitleLocation'):x.convert(changed,E.tostring(root,encoding='unicode'),paths=self.paths,object_name='CRSAPI_FullCatalog')
        field.remove(node);restored=x.convert(changed,E.tostring(root,encoding='unicode'),paths=self.paths,object_name='CRSAPI_FullCatalog');form=x.interface(restored);index,_,_=e.form_collection(form)
        self.assertEqual(s.val(form[1][index+2][7]),'1')


if __name__=='__main__':unittest.main()
