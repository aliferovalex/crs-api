"""Whole ibcmd-compiled configuration bodies with changed root references."""
import base64
import copy
import json
from pathlib import Path
import sys
import types
import unittest
import uuid
from unittest import mock
from xml.etree import ElementTree as E
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / '\u0421\u0435\u0440\u0438\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u044f'))
import compiled_dependencies as dependencies
import compiled_graph as graph
import compiled_metadata as compiled
import configuration_export as export
import native_metadata as s

UNKNOWN = '99999999-9999-4999-8999-999999999999'
VERSION = '88888888-8888-4888-8888-888888888888'


class ConfigurationReferenceTests(unittest.TestCase):
    def setUp(self):
        data = json.loads((Path(__file__).parent / 'fixtures' / 'compiled_configuration_references.json').read_text())
        self.case = json.loads(zlib.decompress(base64.b64decode(data['zlib'])))
        self.oid = self.case['object_id']

    def index(self, stage):
        data = self.case['stages'][stage]
        inventory = {row['id']: dict(row, node=E.fromstring(row['xml'])) for row in data['records']}
        return graph.TypeIndex(inventory, {key: value.encode('utf-8') for key, value in data['image'].items()})

    def content(self, source, target):
        a = s.atom
        objects = {}
        for oid, record in source.inventory.items():
            facts = source.facts(oid) if oid == self.oid else None
            groups = facts.children if facts else {}
            features = facts.features if facts else ()
            m = [a(5), a(oid), a(export.class_id(record, source.inventory)), a(record['parent_id']), a(s.ZERO),
                 a(1), a(0), a(VERSION), a(VERSION), a(record['name'], True), a(0), [a(0)],
                 [a(len(groups))] + [[a(cls), a(len(children))] + [a(child) for child in children] for cls, children in groups.items()],
                 [a(len(features))] + [a(value) for value in features], [a(0)], a('', True), a(0)]
            objects[oid] = [m, [a(0)], [a(0)]]
        docs = objects[self.oid]
        frame = types.SimpleNamespace(docs=docs, saved=copy.deepcopy(docs), metadata=docs[0])
        request = dict(platform='8.5.1.1529', _source_types=source, _compiled_types=target,
                       snapshots={self.oid: 'snapshot'}, originals={self.oid: uuid.UUID(VERSION).bytes_le.hex() + '00000000'})
        change = dict(object_id=self.oid, kind='Configuration', object_xml=target.inventory[self.oid]['xml'])
        with mock.patch.object(compiled.serialization_context, 'read', return_value=frame):
            return compiled.content(request, change, objects, source.image, target.image)

    def test_clear_and_restore_default_language_uses_the_whole_compiled_body(self):
        for old, new in [('before', 'after'), ('after', 'before')]:
            with self.subTest(old=old):
                source, target = self.index(old), self.index(new)
                self.assertNotEqual(compiled.guid_counts(s.Parser(source.image[self.oid].decode()).documents()),
                                    compiled.guid_counts(s.Parser(target.image[self.oid].decode()).documents()))
                result = self.content(source, target)
                self.assertEqual(result.body, target.image[self.oid])
                expected = {child: 1 for children in target.facts(self.oid).children.values() for child in children}
                self.assertEqual(s.metadata_relations(result.docs[0][14]), expected)

    def test_changed_unknown_uuid_is_still_rejected(self):
        source, target = self.index('before'), self.index('after')
        body = s.Parser(target.image[self.oid].decode()).documents()
        body[0].append(s.atom(UNKNOWN))
        target.image[self.oid] = s.native_body_bytes(body)
        with self.assertRaisesRegex(ValueError, 'undeclared configuration references'):
            self.content(source, target)

    def test_own_feature_reference_count_is_still_protected(self):
        source, target = self.index('before'), self.index('after')
        feature = source.facts(self.oid).features[0]
        body = s.Parser(target.image[self.oid].decode()).documents()
        body[0].append(s.atom(feature))
        target.image[self.oid] = s.native_body_bytes(body)
        with self.assertRaisesRegex(ValueError, 'undeclared configuration references'):
            self.content(source, target)

    def test_known_language_requires_its_actual_compiled_identity(self):
        source, target = self.index('after'), self.index('before')
        oid, record = next((oid, row) for oid, row in target.inventory.items() if row['kind'] == 'Language')
        target.image[oid] = target.image[oid].replace(record['name'].encode(), b'WrongName')
        with self.assertRaisesRegex(ValueError, 'name differs'):
            self.content(source, target)

    def test_unchanged_reference_to_a_deleted_identity_is_not_hidden(self):
        source, target = self.index('before'), self.index('after')
        oid = next(oid for oid, row in source.inventory.items() if row['kind'] == 'Language')
        target.inventory.pop(oid)
        with self.assertRaisesRegex(ValueError, 'undeclared configuration references'):
            dependencies.validate_reference_changes(source, target, {oid: 1}, {oid: 1}, self.oid)


if __name__ == '__main__':
    unittest.main()
