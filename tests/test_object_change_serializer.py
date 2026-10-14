"""Whole object edits preserve identities and omitted external streams."""
import base64
import hashlib
import json
import re
import unittest
import uuid
from pathlib import Path
from xml.etree import ElementTree as E
import metadata_serializer as s
import flat_object_serializer as flat
import object_change_serializer as change
import inline_object_xml as inline
import test_object_xml_profiles as objects
import test_register_profiles as registers
import test_catalog_form_serializer as catalog


def fixture(kind='DataProcessor',text=None,externals=False):
    request=catalog.fixture();docs=s.context_metadata(base64.b64decode(request['context']),request['object_id'])
    text=text or objects.xml(kind);oid,name,raw,_=flat.object_xml(text,'8.5.1.1529',kind)
    m=docs[0];m[1],m[2],m[9]=s.atom(oid),s.atom(change.ids.class_id(kind)),s.atom(name,True)
    m[12]=[s.atom(0)];layout=json.loads(Path(flat.__file__).with_name(kind.lower()+'_layout_851.json').read_text(encoding='utf-8'))
    features=inline.features(s.Parser(raw.decode('utf-8-sig')).documents()[0],layout)
    m[13]=[s.atom(len(features))]+[s.atom(key) for key in features]
    if externals:
        version=str(uuid.uuid4());m[11]=[s.atom(2),s.atom(oid+'.0',True),s.atom(version),s.atom(oid+'.2',True),s.atom(version)]
        docs[2]=[s.atom(2),[s.atom(oid+'.0',True),s.atom(version),s.atom(1)],[s.atom(oid+'.2',True),s.atom(version),s.atom(1)]]
    else:m[11]=[s.atom(0)];docs[2]=[s.atom(0)]
    def snapshot():
        meta=s.text_bytes(docs);body=s.compress(raw);manifest=[s.atom(0),s.atom(1),s.atom(oid),s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(body).hexdigest(),True),s.atom(2 if externals else 0)]
        records=[meta,body]
        if externals:
            for stream in (oid+'.0',oid+'.2'):
                data=s.compress(b'original external');records.append(data);manifest.extend([s.atom(stream,True),s.atom(hashlib.sha1(data).hexdigest(),True)])
        return base64.b64encode(s.storage(records,s.text_bytes([manifest]))).decode()
    request.update(repository='Synthetic',repository_version=str(uuid.uuid4()),object_id=oid,object_type=kind,object_xml=text,snapshot=snapshot(),context=base64.b64encode(s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))).decode())
    return request,docs,raw


def unpack(result):
    call=E.fromstring(result['request_xml']);payload=base64.b64decode(call.find('.//{'+s.NS+'}data').text)
    raw=s.inflate(payload[18:]);_,pos=s.read_record(raw,0);storage,_=s.read_record(raw,pos+4)
    meta,pos=s.read_record(storage,12);body,pos=s.read_record(storage,pos)
    return call,s.Parser(meta.decode('utf-8-sig')).documents(),s.inflate(body),storage,pos


class ObjectChangeTests(unittest.TestCase):
    def test_processor_and_report_properties_change_and_clear_without_replacing_modules(self):
        import v8unpack_backend as backend
        for kind in ('DataProcessor','Report'):
            data=json.loads(Path(__file__).with_name('fixtures').joinpath(kind.lower()+'_properties_851.json').read_text(encoding='utf-8'))['cases']
            baseline=next(case for case in data if case['name']=='baseline');combined=next(case for case in data if case['name']=='combined')
            for source,target in ((baseline,combined),(combined,baseline)):
                with self.subTest(kind=kind,target=target['name']):
                    request,metadata,_=fixture(kind,source['xml'],externals=True);request['object_xml']=target['xml']
                    _,docs,raw,_,_=unpack(change.serialize(request))
                    self.assertEqual(backend.signature(s.Parser(raw.decode('utf-8-sig')).documents()),backend.signature(s.Parser(target['body']).documents()))
                    self.assertEqual([s.val(docs[0][11][i]) for i in (1,3)],[s.val(metadata[0][11][i]) for i in (1,3)])
                    for index in (2,4):
                        self.assertEqual(base64.b64decode(s.val(docs[0][11][index])),uuid.UUID(s.val(metadata[0][11][index])).bytes_le+bytes(4))
                    self.assertEqual(s.render(docs[2]),'{0}')

    def test_enum_localized_properties_can_be_changed_and_cleared(self):
        import v8unpack_backend as backend
        fixture_data=json.loads(Path(__file__).with_name('fixtures').joinpath('enum_presentations_851.json').read_text(encoding='utf-8'))
        case=next(case for case in fixture_data['cases'] if case['name']=='combined')
        cleared=case['xml']
        for key in ('ListPresentation','ExtendedListPresentation','Explanation'):
            cleared=re.sub('<'+key+'>.*?</'+key+'>','<'+key+'/>',cleared,flags=re.S)
        request,_,_=fixture('Enum',cleared);request['object_xml']=case['xml']
        _,_,raw,_,_=unpack(change.serialize(request))
        self.assertEqual(backend.signature(s.Parser(raw.decode('utf-8-sig')).documents()),backend.signature(s.Parser(case['body']).documents()))
        request,_,_=fixture('Enum',case['xml']);request['object_xml']=cleared
        _,_,raw,_,_=unpack(change.serialize(request))
        self.assertEqual(backend.signature(s.Parser(raw.decode('utf-8-sig')).documents()),backend.signature(s.Parser(fixture_data['baseline_body']).documents()))

    def test_enum_scalar_changes_match_independent_native_body(self):
        import v8unpack_backend as backend
        cases=json.loads(Path(__file__).with_name('fixtures').joinpath('enum_properties_851.json').read_text(encoding='utf-8'))['cases']
        case=next(case for case in cases if case['name']=='combined')
        source=case['xml'].replace('<UseStandardCommands>true</UseStandardCommands>','<UseStandardCommands>false</UseStandardCommands>').replace('<QuickChoice>false</QuickChoice>','<QuickChoice>true</QuickChoice>').replace('<ChoiceMode>FromForm</ChoiceMode>','<ChoiceMode>BothWays</ChoiceMode>')
        request,_,_=fixture('Enum',source);request['object_xml']=case['xml']
        _,_,raw,_,_=unpack(change.serialize(request))
        self.assertEqual(backend.signature(s.Parser(raw.decode('utf-8-sig')).documents()),backend.signature(s.Parser(case['body']).documents()))

    def test_enum_value_collection_updates_body_and_feature_map(self):
        q='{'+change.c.MD+'}'
        top=E.fromstring(objects.xml('Enum'));children=top[0].find(q+'ChildObjects')
        identifiers=[str(uuid.uuid4()) for _ in range(3)]
        for index,key in enumerate(identifiers[:2]):
            value=E.SubElement(children,q+'EnumValue',uuid=key);props=E.SubElement(value,q+'Properties')
            E.SubElement(props,q+'Name').text='Value'+str(index)
            E.SubElement(props,q+'Comment').text='Original'
        request,_,_=fixture('Enum',E.tostring(top,encoding='unicode'))
        children[0][0].find(q+'Comment').text='Updated'
        children.remove(children[1])
        value=E.SubElement(children,q+'EnumValue',uuid=identifiers[2]);props=E.SubElement(value,q+'Properties')
        E.SubElement(props,q+'Name').text='AddedValue'
        request['object_xml']=E.tostring(top,encoding='unicode')
        _,docs,raw,_,_=unpack(change.serialize(request))
        self.assertEqual([s.val(n) for n in docs[0][13]],['2',identifiers[0],identifiers[2]])
        body=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        layout=json.loads(Path(flat.__file__).with_name('enum_layout_851.json').read_text(encoding='utf-8'))
        self.assertEqual(inline.scopes(body,layout),{identifiers[0]:'EnumValue',identifiers[2]:'EnumValue'})
        self.assertIn('Updated',raw.decode('utf-8-sig'))
        self.assertNotIn(identifiers[1],raw.decode('utf-8-sig'))

    def test_common_properties_in_multiple_profiles(self):
        for kind in objects.PATHS:
            request,_,raw=fixture(kind)
            top=E.fromstring(request['object_xml']);top[0][0].find('{'+change.c.MD+'}Comment').text='Updated'
            request['object_xml']=E.tostring(top,encoding='unicode');_,_,body,_,_=unpack(change.serialize(request))
            source=s.Parser(raw.decode('utf-8-sig')).documents()[0];target=s.Parser(body.decode('utf-8-sig')).documents()[0]
            common=change.at(target,objects.PATHS[kind]);self.assertEqual(s.val(common[4]),'Updated')
            change.replace(target,objects.PATHS[kind]+[4],change.at(source,objects.PATHS[kind]+[4]))
            self.assertEqual(s.render(source),s.render(target))

    def test_complete_inline_collection_replaces_removed_and_changed_fields(self):
        request,_,_=fixture('InformationRegister',registers.xml());top=E.fromstring(request['object_xml']);children=top[0].find(registers.Q+'ChildObjects')
        children.remove(children[2]);children[0][0][0].text='RenamedKey'
        request['object_xml']=E.tostring(top,encoding='unicode');_,docs,body,_,_=unpack(change.serialize(request))
        self.assertEqual({s.val(n) for n in docs[0][13][1:]},set(registers.IDS[:2]))
        self.assertIn('RenamedKey',body.decode('utf-8-sig'));self.assertNotIn(registers.IDS[2],body.decode('utf-8-sig'))

    def test_module_replace_preserves_unspecified_stream_version(self):
        request,source,_=fixture(externals=True);request['modules']={'ObjectModule':'// replaced'}
        call,docs,_,storage,pos=unpack(change.serialize(request));data,end=s.read_record(storage,pos)
        s.validate_storage(storage)
        self.assertIn(b'// replaced',s.inflate(data))
        refs=docs[0][11];self.assertEqual(s.val(refs[0]),'2')
        self.assertEqual(s.val(refs[4]),base64.b64encode(uuid.UUID(s.val(source[0][11][4])).bytes_le+bytes(4)).decode())
        entries=call.findall('.//{'+s.NS+'}externals/{'+s.NS+'}value')
        self.assertEqual([n.find('{'+s.NS+'}second/{'+s.NS+'}action').get('value') for n in entries],['1','0'])

    def test_module_added_to_object_without_source_streams(self):
        request,_,_=fixture();request['modules']={'ObjectModule':'// first module'}
        _,docs,_,storage,pos=unpack(change.serialize(request));data,_=s.read_record(storage,pos)
        self.assertEqual(s.val(docs[0][11][0]),'1');self.assertEqual(s.val(docs[2][0]),'1')
        self.assertIn(b'// first module',s.inflate(data))

    def test_scalar_parameter_type_replaced_from_complete_xml(self):
        request,_,_=fixture('SessionParameter');top=E.fromstring(request['object_xml'])
        import type_description_xml as types
        top[0][0].append(types.export(s.Parser('{"Pattern",{"B"}}').documents()[0],'{'+change.c.MD+'}Type'))
        request['object_xml']=E.tostring(top,encoding='unicode');_,_,raw,_,_=unpack(change.serialize(request))
        layout=json.loads(Path(flat.__file__).with_name('sessionparameter_layout_851.json').read_text(encoding='utf-8'))
        self.assertEqual(s.render(change.at(s.Parser(raw.decode('utf-8-sig')).documents()[0],layout['type_path'])),'{"Pattern",{"B"}}')

    def test_identity_and_generated_identifier_changes_rejected(self):
        request,_,raw=fixture();top=E.fromstring(request['object_xml']);top[0][0][0].text='AnotherName';request['object_xml']=E.tostring(top,encoding='unicode')
        with self.assertRaisesRegex(ValueError,'identity'):change.serialize(request)
        request,_,_=fixture();top=E.fromstring(request['object_xml']);info=E.SubElement(top[0],'{'+change.c.MD+'}InternalInfo')
        for category in ('Object','Manager'):
            node=E.SubElement(info,'{'+change.c.READABLE+'}GeneratedType',name='DataProcessor'+category+'.ProfileTest',category=category)
            for tag in ('TypeId','ValueId'):E.SubElement(node,'{'+change.c.READABLE+'}'+tag).text=str(uuid.uuid4())
        request['object_xml']=E.tostring(top,encoding='unicode')
        with self.assertRaisesRegex(ValueError,'generated identifiers'):change.serialize(request)


if __name__=='__main__':unittest.main()
