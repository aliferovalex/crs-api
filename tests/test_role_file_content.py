"""Whole role files participate in ordinary preparation and object packets."""
import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from dataclasses import asdict
from xml.etree import ElementTree as E
sys.path.insert(0, str(next(p for p in (Path(__file__).resolve().parents[1] / 'src').iterdir() if (p / 'role_rights_xml.py').exists())))
import metadata_definitions as definitions
import metadata_context
import native_metadata as s
import object_file_content as files
import object_creation_serializer as creation
import object_change_serializer as change
import configuration_batch as batch
import role_rights_native
import role_rights_xml as rights
import test_object_xml_profiles as objects
import test_object_change_serializer as changes
from test_managed_form_creation import store
from test_role_rights_xml import source


def case():
    return json.loads(Path(__file__).with_name('fixtures').joinpath('role_rights_relations_851.json').read_text(encoding='utf-8'))


class RoleFileContentTests(unittest.TestCase):
    def test_complete_file_and_relations_follow_independent_native_descriptors(self):
        data = case()
        for sample in data['samples']:
            with self.subTest(name=sample['name']):
                encoded = base64.b64encode(sample['xml'].encode('utf-8')).decode()
                content = files.convert('Role', sample['definition_xml'], {'Rights': encoded}, {'metadata_definitions': data['definitions']})
                expected = s.Parser(sample['native']).documents()[0]
                actual = s.Parser(content['Rights'].data.decode('utf-8-sig')).documents()[0]
                self.assertEqual(s.render(expected[2:]), s.render(actual[2:]))
                metadata = [s.atom(0) for _ in range(17)]; metadata[3] = s.atom(sample['parent_id'])
                files.apply_relations(metadata, content)
                self.assertEqual(s.metadata_relations(metadata[14]), sample['relations'])
                self.assertEqual(set(sample['relations']), set(role_rights_native.file_references(content['Rights'].data)) | {sample['parent_id']})

    def test_creation_adds_a_complete_role_stream_to_the_common_packet(self):
        request = objects.request('Role'); root = request['object_id']
        context = metadata_context.context_objects(request['context']); name = s.val(context[root][0][9])
        entry = definitions.Definition(root, 'Configuration', name, 'Configuration.' + name, s.ZERO, root, True)
        index = definitions.Index([entry])
        xml = source('<object><name>Configuration.' + name + '</name><right><name>ThinClient</name><value>true</value></right></object>')
        request.update(file_data={'Rights': base64.b64encode(xml.encode()).decode()}, _metadata_definitions=index)
        result = creation.serialize(request); _, records = batch.read_packet(result['data'])
        record = next(row for row in records if row.object_id == result['object_id'])
        self.assertEqual({name for name, _ in record.externals}, {record.object_id + '.0'})
        metadata = s.Parser(record.metadata.decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.metadata_relations(metadata[14]), {root: 1})
        self.assertIn(root, role_rights_native.file_references(s.inflate(record.externals[0][1])))
        request.pop('_metadata_definitions'); request['metadata_definitions'] = [asdict(entry)]
        creation.serialize(request)
        request['metadata_definitions'][0]['name'] = 'Different'
        request['metadata_definitions'][0]['qualified_name'] = 'Configuration.Different'
        with self.assertRaisesRegex(ValueError, 'differs from current repository'):
            creation.serialize(request)

    def test_empty_replacement_clears_old_relations_and_preserves_other_streams(self):
        sample = case()['samples'][0]
        request, docs, raw = changes.fixture('Role', sample['definition_xml'])
        oid = request['object_id']; other = oid + '.9'; version = str(uuid.uuid4()); old = str(uuid.uuid4())
        docs[0][11] = [s.atom(1), s.atom(other, True), s.atom(version)]
        docs[0][14].insert(2, s.atom(old)); docs[0][14].append(s.atom(1)); docs[0][14][0] = s.atom(2)
        docs[2] = [s.atom(0)]
        request.update(snapshot=store(docs, raw), context=base64.b64encode(s.storage([s.text_bytes(docs)], s.text_bytes([[s.atom(0)]]))).decode(), file_data={'Rights': base64.b64encode(source().encode()).decode()})
        _, updated, body, storage, pos = changes.unpack(change.serialize(request))
        self.assertEqual(body, raw)
        self.assertEqual(s.metadata_relations(updated[0][14]), {s.val(docs[0][3]): 1})
        self.assertEqual(s.val(updated[0][11][1]), other)
        external, _ = s.read_record(storage, pos)
        self.assertEqual(role_rights_native.file_references(s.inflate(external)), frozenset())

    def test_preparation_collects_only_referenced_definitions_from_the_export(self):
        data = case(); sample = next(row for row in data['samples'] if row['name'] == 'ProbeFieldRLS')
        rows = {row['kind']: row for row in data['definitions'] if row['kind'] in ('Configuration', 'Catalog', 'Attribute')}
        q = definitions.Q
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = E.Element(q + 'MetaDataObject', version='2.21'); config = E.SubElement(root, q + 'Configuration', uuid=rows['Configuration']['object_id'])
            E.SubElement(E.SubElement(config, q + 'Properties'), q + 'Name').text = rows['Configuration']['name']
            children = E.SubElement(config, q + 'ChildObjects')
            E.SubElement(children, q + 'Catalog').text = rows['Catalog']['name']; E.SubElement(children, q + 'Role').text = sample['name']
            E.ElementTree(root).write(base / 'Configuration.xml', encoding='utf-8')
            catalog = E.Element(q + 'MetaDataObject', version='2.21'); node = E.SubElement(catalog, q + 'Catalog', uuid=rows['Catalog']['object_id'])
            E.SubElement(E.SubElement(node, q + 'Properties'), q + 'Name').text = rows['Catalog']['name']
            field = E.SubElement(E.SubElement(node, q + 'ChildObjects'), q + 'Attribute', uuid=rows['Attribute']['object_id'])
            E.SubElement(E.SubElement(field, q + 'Properties'), q + 'Name').text = rows['Attribute']['name']
            (base / 'Catalogs').mkdir(); E.ElementTree(catalog).write(base / 'Catalogs' / (rows['Catalog']['name'] + '.xml'), encoding='utf-8')
            path = base / 'Roles' / (sample['name'] + '.xml'); path.parent.mkdir(); path.write_text(sample['definition_xml'], encoding='utf-8')
            companion = path.with_suffix('') / 'Ext/Rights.xml'; companion.parent.mkdir(parents=True); companion.write_text(sample['xml'], encoding='utf-8')
            values = files.companion(path, 'Role', sample['definition_xml'])
            result = files.definition_context(path, 'Role', values, {})
            self.assertEqual({row['kind'] for row in result['metadata_definitions']}, {'Configuration', 'Catalog', 'Attribute'})
            self.assertEqual(len(result['metadata_definitions']), 3)
            self.assertEqual(role_rights_native.file_references(files.convert('Role', sample['definition_xml'], values, result)['Rights'].data),
                             frozenset({rows['Catalog']['object_id'], rows['Attribute']['object_id']}))

    def test_metadata_only_changes_do_not_clear_existing_file_relations(self):
        metadata = [s.atom(0)] * 17; metadata[3] = s.atom(str(uuid.uuid4())); metadata[14] = [s.atom(0)]
        original = copy.deepcopy(metadata)
        files.apply_relations(metadata, {})
        self.assertEqual(s.render(metadata), s.render(original))


if __name__ == '__main__':
    unittest.main()
