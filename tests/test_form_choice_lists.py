"""Whole ChoiceList conversion with independent native form interfaces."""
import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('managed_form_rules.py')).parent))
import metadata_serializer as s
import managed_form_xml as x
import managed_form_elements as elements
import v8unpack_backend as b
import choice_list_xml as choices
import typed_value_xml as values
import appearance_xml


class ChoiceListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=Path(__file__).with_name('fixtures')
        cls.fixture=json.loads((folder/'form_choice_lists_851.json').read_text(encoding='utf-8'))
        base=json.loads((folder/'form_rules_851.json').read_text(encoding='utf-8'))
        cls.paths=x.ObjectPaths({k:s.Parser(v).documents()[0] for k,v in base['paths'].items()})
        cls.paths.types=base['types'];cls.paths.tables=set(base['tables'])

    def convert(self,kind,xml,source=None):
        return x.convert(source or self.fixture['bases'][kind].encode('utf-8'),xml,paths=self.paths,object_name='CRSAPI_FullCatalog')

    def case(self,kind,value):
        return next(c for c in self.fixture['cases'] if c['kind']==kind and c['value']==value)

    def native_list(self,raw):
        form=x.interface(raw);index,_,_=elements.form_collection(form)
        return form[1][index+2][39][1]

    def test_complete_interfaces_match_34_native_samples(self):
        self.assertEqual(len(self.fixture['cases']),34)
        for case in self.fixture['cases']:
            with self.subTest(kind=case['kind'],name=case['name'],value=case['value']):
                result=self.convert(case['kind'],case['xml']);signature=b.signature(s.Parser(result.decode('utf-8-sig')).documents())
                self.assertEqual(hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest(),case['sha256'])

    def test_removal_and_empty_xml_restore_choice_list_default(self):
        for kind in self.fixture['bases']:
            changed=self.convert(kind,self.case(kind,'checked-2')['xml'])
            for value in ('baseline','list-0'):
                restored=self.convert(kind,self.case(kind,value)['xml'],changed)
                self.assertEqual(b.signature(x.interface(restored)),b.signature(x.interface(self.fixture['bases'][kind].encode('utf-8'))))

    def test_order_duplicates_captions_and_check_states_are_preserved(self):
        kind='RadioButtonField';root=E.fromstring(self.case(kind,'checked-2')['xml']);node=root.find('.//'+x.Q+'ChoiceList')
        second=copy.deepcopy(node[0]);second.find(choices.XR+'Value/'+x.Q+'Value').text='Second';second.find(choices.XR+'CheckState').text='1';node.append(second)
        # Keep required QName declarations when serializing ElementTree nodes.
        root.set('xmlns:xs',values.XSD);root.set('xmlns',x.NS)
        first=self.convert(kind,E.tostring(root,encoding='unicode'));node[:]=[second,node[0]]
        reordered=self.convert(kind,E.tostring(root,encoding='unicode'),first);native=self.native_list(reordered)
        self.assertEqual(s.val(native[1]),'2')
        self.assertEqual([s.val(native[i][2][2][1]) for i in (3,5)],['Second','Value'])
        self.assertEqual([s.val(native[i][0]) for i in (6,7)],['1','2'])
        self.assertEqual(s.val(native[3][2][5][2][1]),'Caption')
        node.append(copy.deepcopy(second));duplicate=self.native_list(self.convert(kind,E.tostring(root,encoding='unicode'),reordered))
        self.assertEqual(s.val(duplicate[1]),'3');self.assertEqual(s.val(duplicate[7][2][2][1]),'Second')

    def test_namespace_aliases_do_not_change_native_values(self):
        case=self.case('InputField','list-6');xml=case['xml']
        alias=xml.replace('xmlns:xs=','xmlns:data=').replace('xs:string','data:string').replace('xs:decimal','data:decimal').replace('xs:boolean','data:boolean')
        alias=alias.replace('<Form ', '<Form xmlns:forms="'+x.NS+'" ',1).replace('"FormChoiceListDesTimeValue"','"forms:FormChoiceListDesTimeValue"')
        self.assertEqual(b.signature(x.interface(self.convert('InputField',alias))),b.signature(x.interface(self.convert('InputField',xml))))

    def test_scalar_choice_lists_from_demo_match_with_normalized_line_endings(self):
        fixture=json.loads((Path(__file__).with_name('fixtures')/'form_demo_field_kinds_851.json').read_text(encoding='utf-8'));matched=0
        for case in fixture['cases']:
            if case['kind']!='RadioButtonField':continue
            # The saved subtree's QName attributes refer to declarations in the
            # full original XML; supply those known namespace URIs explicitly.
            root=E.fromstring(case['xml']);node=root.find(x.Q+'ChoiceList')
            bindings={'':x.NS,'xr':choices.XR[1:-1],'xs':values.XSD}
            if any(v.get(values.XSI+'type')=='xr:DesignTimeRef' for v in node.iter()):continue
            entry=s.Parser(case['native']).documents()[0];header=elements.field_header_size(entry)
            actual=choices.read(node,bindings);expected=entry[39+header][1]
            def normalized(value):
                if isinstance(value,list):return [normalized(v) for v in value]
                return value.quoted,s.val(value).replace('\r\n','\n')
            self.assertEqual(normalized(actual),normalized(expected));matched+=1
        self.assertEqual(matched,2)

    def test_unresolved_references_invalid_scalars_and_structures_fail(self):
        case=self.case('InputField','list-1')
        for value_type,text in [('xs:decimal','NaN'),('xs:boolean','1'),('xs:dateTime','2026-02-30T00:00:00'),('xs:dateTime','2026-10-13T00:00:00Z'),('xr:DesignTimeRef','Enum.Unknown.EnumValue.Item')]:
            root=E.fromstring(case['xml']);root.set('xmlns:xs',values.XSD);root.set('xmlns:xr',choices.XR[1:-1]);root.set('xmlns',x.NS);value=root.find('.//'+x.Q+'ChoiceList/'+choices.XR+'Item/'+choices.XR+'Value/'+x.Q+'Value');value.set(values.XSI+'type',value_type);value.text=text
            with self.subTest(value_type=value_type),self.assertRaises(ValueError):self.convert('InputField',E.tostring(root,encoding='unicode'))
        root=E.fromstring(case['xml']);root.set('xmlns:xs',values.XSD);root.set('xmlns',x.NS);item=root.find('.//'+choices.XR+'Item');item.append(copy.deepcopy(item[0]))
        with self.assertRaises(ValueError):self.convert('InputField',E.tostring(root,encoding='unicode'))

    def test_decimal_precision_is_not_rounded_by_python_context(self):
        node=E.Element(x.Q+'Value',{values.XSI+'type':'num:decimal'});node.text='12345678901234567890123456789012345678'
        self.assertEqual(s.val(values.read(node,{'num':values.XSD})[1]),node.text)
        node.text+='9'
        with self.assertRaises(ValueError):values.read(node,{'num':values.XSD})

    def test_v47_radio_uses_same_choice_list_and_layout_rules(self):
        kind='RadioButtonField';raw=self.fixture['bases'][kind].encode('utf-8');form=x.interface(raw);index,_,_=elements.form_collection(form);entry=form[1][index+2];entry[0]=s.atom(47);del entry[-2:]
        old=b.assemble(b.to_model([form]));xml=self.case(kind,'checked-1')['xml']
        self.assertEqual(b.signature(x.interface(self.convert(kind,xml,old))),b.signature(x.interface(self.convert(kind,xml,raw))))


if __name__=='__main__':unittest.main()
