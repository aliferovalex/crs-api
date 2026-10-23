"""Existing constants use whole-object change with stable generated types."""
import copy
import unittest
from xml.etree import ElementTree as E
import test_object_creation_serializer as constants
import test_object_change_serializer as changes
import metadata_object_xml as metadata
import native_metadata as s
import type_description_xml as types


class ConstantChangeTests(unittest.TestCase):
    def fixture(self):
        return changes.fixture('Constant',constants.xml())

    def test_whole_xml_changes_type_and_common_properties_preserving_generated_ids(self):
        request,before,raw=self.fixture();source=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        top=E.fromstring(request['object_xml']);props=top[0].find(metadata.Q+'Properties')
        props.find(metadata.Q+'Comment').text='Changed existing constant'
        props.remove(props.find(metadata.Q+'Type'));pattern=s.Parser('{"Pattern",{"N",12,3,1}}').documents()[0]
        props.append(types.export_metadata(pattern,metadata.Q+'Type'));request['object_xml']=E.tostring(top,encoding='unicode')
        _,docs,body,_,_=changes.unpack(changes.change.serialize(request));target=s.Parser(body.decode('utf-8-sig')).documents()[0]
        profile=metadata.profiles.layout('Constant')
        self.assertEqual(s.render(metadata.at(target,profile['type_path'])),s.render(pattern))
        self.assertEqual([s.val(target[1][slot]) for slot in profile['generated_slots']],[s.val(source[1][slot]) for slot in profile['generated_slots']])
        self.assertEqual(s.val(metadata.at(target,profile['common_path'])[4]),'Changed existing constant')
        self.assertEqual(s.val(docs[0][1]),constants.CID);self.assertEqual(s.render(docs[0][13]),'{0}')
        self.assertEqual(s.render(docs[0][14]),s.render(before[0][14]))

    def test_generated_type_mutation_and_unsupported_properties_are_rejected(self):
        request,_,raw=self.fixture();source=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        top=metadata.export(source,{},request['platform'],'Constant')
        top[0].find(metadata.Q+'InternalInfo')[0][0].text='dddddddd-dddd-4ddd-8ddd-dddddddddddd'
        with self.assertRaisesRegex(ValueError,'generated identifiers'):metadata.change(E.tostring(top,encoding='unicode'),request['platform'],'Constant',source)
        top=E.fromstring(request['object_xml']);E.SubElement(top[0].find(metadata.Q+'Properties'),metadata.Q+'ToolTip').text='unmapped'
        with self.assertRaisesRegex(ValueError,'Unsupported Constant property'):metadata.change(E.tostring(top,encoding='unicode'),request['platform'],'Constant',source)

    def test_modern_change_is_not_enabled_by_a_legacy_proof(self):
        request,_,raw=self.fixture();source=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        with self.assertRaisesRegex(ValueError,'verified platform profile'):metadata.change(request['object_xml'],'8.5.4.1878','Constant',source)


if __name__=='__main__':unittest.main()
