"""External compiler metadata checks without native XML property writers."""
import copy
import types
import unittest
import uuid
from unittest import mock

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))

import compiled_metadata as compiled
import native_metadata as s
import json
from pathlib import Path
import metadata_identifiers
import native_form_profiles

OID = '11111111-1111-4111-8111-111111111111'
PARENT = '22222222-2222-4222-8222-222222222222'
FEATURE = '33333333-3333-4333-8333-333333333333'
GENERATED = '44444444-4444-4444-8444-444444444444'


def xml(value='AutoFill', extra=''):
    return ('<MetaDataObject xmlns="' + compiled.Q[1:-1] + '" version="2.21"><Document uuid="' + OID + '">'
            '<InternalInfo/><Properties><Name>TestDocument</Name><Comment/>'
            '<SequenceFilling>' + value + '</SequenceFilling>' + extra + '</Properties><ChildObjects/></Document></MetaDataObject>')


class ContractTests(unittest.TestCase):
    def frame(self):
        a = s.atom
        m = [a(5), a(OID), a(GENERATED), a(PARENT), a(s.ZERO), a(1), a(0), a(GENERATED), a(GENERATED),
             a('TestDocument', True), a(0), [a(0)], [a(0)], [a(1), a(FEATURE)], [a(1), a(PARENT), a(1)], a('descriptor', True), a(0)]
        docs = [m, [a(0)], [a(0)]]
        return types.SimpleNamespace(saved=copy.deepcopy(docs), docs=docs, metadata=m)

    def test_complete_owner_xml_has_no_per_property_admission_policy(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);(directory/'Document.xml').write_text(xml(),encoding='utf-8')
            change=dict(kind='Document',object_xml=xml('AnotherCompilerValue',extra='<ApplicationProperty>Opaque</ApplicationProperty>'))
            compiled.validate_xml(change,directory,directory,Path('Document.xml'))
            self.assertIn('_owner_contract',change)

    def test_whole_form_accepts_nested_control_kinds_and_events_without_templates(self):
        form='<Form xmlns="'+compiled.FORM[1:-1]+'"><ChildItems><UsualGroup name="Group" id="1"><ChildItems><Button name="Run" id="2"><Events><Event name="Click">Run</Event></Events></Button><Table name="Rows" id="3"><Events><Event name="Click">Rows</Event></Events><ChildItems><InputField name="Cell" id="4"><DataPath>Local.Value</DataPath></InputField></ChildItems></Table></ChildItems></UsualGroup></ChildItems><Attributes><Attribute name="Local" id="1"/></Attributes></Form>'
        self.assertEqual(compiled.validate_form_xml(form).tag,compiled.FORM+'Form')
        with self.assertRaisesRegex(ValueError,'control ID'):
            compiled.validate_form_xml(form.replace('id="4"','id="2"'))

    def test_column_identity_scopes_and_attribute_names_are_not_control_events(self):
        form='<Form xmlns="'+compiled.FORM[1:-1]+'"><Attributes><Attribute name="One" id="1"><Columns><Column name="Value" id="1"/></Columns></Attribute><Attribute name="Two" id="2"><Columns><Column name="Value" id="1"/></Columns></Attribute></Attributes></Form>'
        compiled.validate_form_xml(form)
        with self.assertRaisesRegex(ValueError,'Duplicate compiled name'):
            compiled.validate_form_xml(form.replace('name="Two"','name="One"'))

    def test_native_form_without_main_is_allowed_but_declared_references_must_exist(self):
        fixture=json.loads(Path(__file__).with_name('fixtures').joinpath('compiled_owners.json').read_text(encoding='utf-8'))
        owner=s.Parser(fixture['Catalog']['before']).documents()[0]
        raw=native_form_profiles.owner_profiles()['Catalog']['external_template'].encode()
        xml='<Form xmlns="'+compiled.FORM[1:-1]+'"><Attributes/></Form>'
        compiled.validate_form_interface(xml,owner,'Catalog',raw,{})
        with mock.patch.object(compiled.metadata_references,'resolve',return_value={'cfg:CatalogRef.Other':GENERATED}):
            with self.assertRaisesRegex(ValueError,'missing declared native reference'):
                compiled.validate_form_interface(xml,owner,'Catalog',raw,{})

    def test_new_native_main_cannot_be_hidden_in_a_no_main_xml(self):
        fixture=json.loads(Path(__file__).with_name('fixtures').joinpath('compiled_owners.json').read_text(encoding='utf-8'))
        owner=s.Parser(fixture['Catalog']['before']).documents()[0]
        raw=native_form_profiles.owner_profiles()['Catalog']['external_template'].encode()
        xml='<Form xmlns="'+compiled.FORM[1:-1]+'"><Attributes/></Form>'
        form=compiled.native_form_reader.interface(raw)
        fake=[s.atom(0) for _ in range(11)];fake[10]=s.atom(1)
        form[3]=[s.atom(0),s.atom(1),fake]
        with mock.patch.object(compiled.native_form_reader,'interface',return_value=form):
            with self.assertRaisesRegex(ValueError,'undeclared main'):
                compiled.validate_form_interface(xml,owner,'Catalog',raw,{})

    def test_form_reference_proof_uses_authoritative_storage_without_extra_snapshots(self):
        fixture=json.loads(Path(__file__).with_name('fixtures').joinpath('compiled_owners.json').read_text(encoding='utf-8'))
        owner=s.Parser(fixture['Catalog']['before']).documents()[0]
        raw=native_form_profiles.owner_profiles()['Catalog']['external_template'].encode()
        xml='<Form xmlns="'+compiled.FORM[1:-1]+'"><Attributes/></Form>'
        with mock.patch.object(compiled.serialization_context,'decode',return_value=b'verified storage'),mock.patch.object(compiled.metadata_references,'resolve',return_value={}) as resolve:
            request=dict(storage='encoded storage')
            compiled.validate_form_interface(xml,owner,'Catalog',raw,request)
            resolve.assert_called_once_with(xml,request,b'verified storage')

    def test_independent_body_change_never_calls_xml_serializers_and_preserves_graph(self):
        frame = self.frame()
        source = ('{1,{40,' + OID + ',' + GENERATED + ',{' + FEATURE + '},0}}').encode()
        target = source[:-3] + b'1}}'  # only a scalar atom changes
        request = dict(snapshots={OID: 'snapshot'}, originals={OID: uuid.UUID(GENERATED).bytes_le.hex() + '00000000'})
        objects = {OID: frame.docs, PARENT: frame.docs}
        with mock.patch.object(compiled.serialization_context, 'read', return_value=frame):
            result = compiled.content(request, dict(object_id=OID, kind='Document'), objects, {OID: source}, {OID: target})
        self.assertEqual(result.body, target)
        self.assertEqual(s.render(result.docs[0][13]), '{1,' + FEATURE + '}')
        self.assertEqual(s.metadata_relations(result.docs[0][14]), {PARENT: 1})
        self.assertEqual(result.streams, [])

    def test_owner_module_payloads_use_the_declared_class_streams(self):
        for kind,suffix in [('Catalog','.3'),('Document','.2'),('DataProcessor','.2'),('Report','.2')]:
            with self.subTest(kind=kind):
                frame=self.frame();source=('{1,{'+OID+','+FEATURE+','+GENERATED+'}}').encode()
                request=dict(snapshots={OID:'snapshot'},originals={OID:uuid.UUID(GENERATED).bytes_le.hex()+'00000000'})
                before={OID:source};after=dict(before,**{OID+'.0':b'object module',OID+suffix:b'manager module'})
                with mock.patch.object(compiled.serialization_context,'read',return_value=frame):
                    result=compiled.content(request,dict(object_id=OID,kind=kind),{OID:frame.docs,PARENT:frame.docs},before,after)
                self.assertEqual({k:s.inflate(v) for k,v in result.streams},{OID+'.0':b'object module',OID+suffix:b'manager module'})
                self.assertEqual(s.metadata_relations(result.docs[0][14]),{PARENT:1})
                self.assertTrue(all(row['action']==1 for row in result.externals))

    def test_compiler_cannot_reassign_native_uuid_or_feature(self):
        frame = self.frame()
        source = ('{1,{' + OID + ',' + FEATURE + ',' + GENERATED + '}}').encode()
        target = source.replace(FEATURE.encode(), PARENT.encode())
        request = dict(snapshots={OID: 'snapshot'}, originals={OID: uuid.UUID(GENERATED).bytes_le.hex() + '00000000'})
        with mock.patch.object(compiled.serialization_context, 'read', return_value=frame):
            with self.assertRaisesRegex(ValueError, 'UUIDs or native references'):
                compiled.content(request, dict(object_id=OID, kind='Document'), {OID: frame.docs, PARENT: frame.docs}, {OID: source}, {OID: target})

    def test_snapshot_graph_mismatch_and_missing_owner_relation_are_rejected(self):
        frame = self.frame()
        frame.saved[0][13][1] = s.atom(GENERATED)
        with self.assertRaisesRegex(ValueError, 'features or relations'):
            compiled.validate_graph(frame, OID, {PARENT: frame.docs})
        frame = self.frame(); frame.metadata[14][-1] = s.atom(0); frame.saved = copy.deepcopy(frame.docs)
        with self.assertRaisesRegex(ValueError, 'owner relation'):
            compiled.validate_graph(frame, OID, {PARENT: frame.docs})

    def owner_xml(self, kind, ids):
        attributes = ''.join('<Attribute uuid="' + oid + '"><Properties><Name>Field' + str(index) + '</Name><Type><v8:Type>xs:string</v8:Type><v8:StringQualifiers><v8:Length>30</v8:Length><v8:AllowedLength>Variable</v8:AllowedLength></v8:StringQualifiers></Type></Properties></Attribute>' for index, oid in enumerate(ids))
        return ('<MetaDataObject xmlns="' + compiled.Q[1:-1] + '" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xs="http://www.w3.org/2001/XMLSchema" version="2.21"><' + kind + ' uuid="' + OID + '"><Properties><Name>TestDocument</Name></Properties><ChildObjects>' + attributes + '</ChildObjects></' + kind + '></MetaDataObject>')

    def compiled_feature_change(self, kind, final_ids, tamper_generated=False):
        old, new = self.owner_xml(kind, [FEATURE]), self.owner_xml(kind, final_ids)
        fixture = json.loads(Path(__file__).with_name('fixtures').joinpath('compiled_owners.json').read_text(encoding='utf-8'))[kind]
        key = 'delete' if not final_ids else 'collision' if PARENT in final_ids else 'add' if len(final_ids)>1 else 'before'
        source = fixture['before'].encode('utf-8')
        target = fixture[key].encode('utf-8')
        if tamper_generated:
            target = target.replace(fixture['generated'].encode(), b'66666666-6666-4666-8666-666666666666')
        frame = self.frame(); frame.metadata[2] = s.atom(metadata_identifiers.class_id(kind)); frame.saved = copy.deepcopy(frame.docs)
        request = dict(platform='8.5.1.1529', snapshots={OID: 'snapshot'}, originals={OID: uuid.UUID(GENERATED).bytes_le.hex() + '00000000'})
        change = dict(object_id=OID, kind=kind, object_xml=new, _owner_contract=True)
        with mock.patch.object(compiled.serialization_context, 'read', return_value=frame), \
                mock.patch.object(compiled.metadata_type_references, 'reconcile', side_effect=lambda *args: args[4]):
            return compiled.content(request, change, {OID: frame.docs, PARENT: frame.docs}, {OID: source}, {OID: target})

    def test_native_feature_addition_and_removal_share_one_mechanism_for_four_owners(self):
        added = '55555555-5555-4555-8555-555555555555'
        for kind in sorted(compiled.OWNERS):
            with self.subTest(kind=kind):
                result = self.compiled_feature_change(kind, [FEATURE, added])
                self.assertEqual({s.val(v) for v in result.docs[0][13][1:]}, {FEATURE, added})
                result = self.compiled_feature_change(kind, [])
                self.assertEqual(s.render(result.docs[0][13]), '{0}')

    def test_new_feature_cannot_reuse_an_existing_object_uuid(self):
        with self.assertRaisesRegex(ValueError, 'collides'):
            self.compiled_feature_change('Document', [FEATURE, PARENT])

    def test_control_ids_and_dangling_paths_are_rejected(self):
        form = '<Form xmlns="' + compiled.FORM[1:-1] + '"><ChildItems><InputField name="First" id="1"><DataPath>Object.Value</DataPath></InputField><InputField name="Second" id="1"><DataPath>Object.Other</DataPath></InputField></ChildItems></Form>'
        with self.assertRaisesRegex(ValueError, 'control ID'):
            compiled.validate_form_xml(form)

    def test_generated_type_identity_cannot_change_with_an_attribute_addition(self):
        with self.assertRaisesRegex(ValueError, 'generated type identity'):
            self.compiled_feature_change('Document', [FEATURE], tamper_generated=True)

    def test_compiler_reference_patterns_must_match_resolved_metadata_types(self):
        with mock.patch.object(compiled.metadata_type_references, 'resolve', return_value={'cfg:CatalogRef.Other': GENERATED}):
            with self.assertRaisesRegex(ValueError, 'reference type IDs'):
                self.compiled_feature_change('Document', [FEATURE])

    def test_final_form_binding_reader_rejects_a_removed_attribute(self):
        text = self.owner_xml('Document', [FEATURE])
        raw = json.loads(Path(__file__).with_name('fixtures').joinpath('compiled_owners.json').read_text(encoding='utf-8'))['Document']['before'].encode('utf-8')
        body = s.Parser(raw.decode('utf-8-sig')).documents()[0]
        form = '<Form xmlns="' + compiled.FORM[1:-1] + '" xmlns:v8="http://v8.1c.ru/8.1/data/core"><ChildItems><InputField name="Field" id="2"><DataPath>Object.Field0</DataPath></InputField></ChildItems><Attributes><Attribute name="Object" id="1"><Type><v8:Type>cfg:DocumentObject.TestDocument</v8:Type></Type><MainAttribute>true</MainAttribute></Attribute></Attributes></Form>'
        self.assertTrue(compiled.validate_form_paths(form, body, 'Document'))
        self.assertTrue(compiled.validate_form_paths(form.replace('Object.Field0','Local.Value'),body,'Document'))
        self.assertIsNone(compiled.validate_form_paths('<Form xmlns="'+compiled.FORM[1:-1]+'"><Attributes/></Form>',body,'Document'))
        with self.assertRaisesRegex(ValueError, 'unavailable final DataPath'):
            compiled.validate_form_paths(form.replace('Object.Field0', 'Object.Removed'), body, 'Document')


if __name__ == '__main__':
    unittest.main()
