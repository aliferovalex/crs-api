"""Design-time values resolved from a verified ibcmd CF, without XML writing."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from xml.etree import ElementTree as E
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'Сериализация'))
import compiled_graph as graph
import compiled_metadata as compiled
import configuration_export as export
import metadata_identifiers as ids
import metadata_references as references
import native_metadata as s
import native_predefined_reader as predefined


def reference_request(index, source=None):
    """Protocol identity context for already verified compiler images."""
    a = s.atom; docs = []
    for oid, record in index.inventory.items():
        features = graph.features(record)
        m = [a(5), a(oid), a(export.class_id(record, index.inventory)), a(record['parent_id']), a(s.ZERO),
             a(1), a(0), a(s.ZERO), a(s.ZERO), a(record['name'], True), a(0), [a(0)], [a(0)],
             [a(len(features))] + [a(value) for value in features], [a(0)], a('', True), a(0)]
        docs.append(s.text_bytes([m, [a(0)], [a(0)]]))
    return dict(context=base64.b64encode(s.storage(docs, s.text_bytes([[a(0)]]))).decode(),
                platform='8.5.1.1529', _compiled_types=index, _source_types=source or index)


class PredefinedReferenceTests(unittest.TestCase):
    def setUp(self):
        saved = json.loads((Path(__file__).parent / 'fixtures' / 'compiled_predefined_references.json').read_text(encoding='utf-8'))
        self.case = json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))
        inventory = {row['id']: dict(row, node=E.fromstring(row['xml'])) for row in self.case['records']}
        self.image = {name: base64.b64decode(raw) for name, raw in self.case['image'].items()}
        self.index = graph.TypeIndex(inventory, self.image)
        self.owner = self.case['owner_id']; self.xml = self.case['form_xml']
        self.request = reference_request(self.index)

    def test_compiled_catalog_values_and_empty_ref_validate_the_whole_form(self):
        values = references.resolve_values(self.xml, self.request)
        expected = predefined.read(self.image[self.owner + '.1c'], 'Catalog')
        type_id, oid = self.index.reference('cfg:CatalogRef.CRSAPI_FormOwner')
        self.assertEqual(oid, self.owner)
        self.assertEqual(values, {'Catalog.CRSAPI_FormOwner.' + name: (type_id, value) for name, value in
                                 list(expected.items()) + [('EmptyRef', s.ZERO)]})
        owner = s.Parser(self.image[self.owner].decode('utf-8-sig')).documents()[0]
        compiled.validate_form_interface(self.xml, owner, 'Catalog', self.image[self.case['form_id'] + '.0'], self.request)

    def test_reference_plan_selects_the_owner_once(self):
        plan = references.plan(dict(self.request, xml=self.xml))
        self.assertEqual(plan['objects'], [dict(object_id=self.owner, name='CRSAPI_FormOwner')])

    def test_dependencies_are_added_and_removed_without_losing_opaque_links(self):
        parent = next(oid for oid, row in self.index.inventory.items() if row['kind'] == 'Catalog' and oid != self.owner)
        opaque = '77777777-7777-4777-8777-777777777777'
        result = references.form_relations(self.xml, self.request, parent, {opaque: 1})
        self.assertEqual(s.metadata_relations(result), {parent: 1, self.owner: 1, opaque: 1})
        result = references.form_relations('<Form/>', self.request, parent, s.metadata_relations(result),
                                          self.image[self.case['form_id'] + '.0'])
        self.assertEqual(s.metadata_relations(result), {parent: 1, opaque: 1})

    def test_null_and_named_empty_values_do_not_invent_an_object_identity(self):
        xml = '<Value xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xr="' + references.XR + '" xsi:type="xr:DesignTimeRef"/>'
        self.assertEqual(references.resolve_values(xml, {}), {'': (s.ZERO, s.ZERO)})
        self.assertEqual(references.plan({'xml': xml}), {'objects': []})
        for row in self.index.inventory.values():
            if row['kind'] not in ('Document', 'DataProcessor', 'Report'):continue
            text = row['kind'] + '.' + row['name'] + '.EmptyRef'
            candidate = xml.replace('/>', '>' + text + '</Value>')
            if 'cfg:' + row['kind'] + 'Ref.' + row['name'] in self.index.aliases:
                self.assertEqual(references.resolve_values(candidate, self.request)[text][1], s.ZERO)

    def test_missing_named_value_missing_stream_and_wrong_family_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'predefined value is missing'):
            references.resolve_values(self.xml.replace('CRSAPI_FormOwner.First', 'CRSAPI_FormOwner.Absent'), self.request)
        raw = self.image.pop(self.owner + '.1c')
        with self.assertRaisesRegex(ValueError, 'stream is missing'):
            references.resolve_values(self.xml, self.request)
        self.image[self.owner + '.1c'] = raw.replace(b'{0,', b'{2,', 1)
        with self.assertRaisesRegex(ValueError, 'family differs'):
            references.resolve_values(self.xml, self.request)

    def test_renamed_deleted_and_ambiguous_predefined_items_are_not_guessed(self):
        docs = s.Parser(self.image[self.owner + '.1c'].decode('utf-8-sig')).documents()
        # The compiler fixture stores its tail at table level.
        items = docs[0][1][2][16][2][-1][2:]
        for duplicate in ('name', 'uuid'):
            damaged = copy.deepcopy(docs)
            children = damaged[0][1][2][16][2][-1][2:]
            slot = 6 if duplicate == 'name' else 3
            children[1][slot] = copy.deepcopy(children[0][slot])
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(ValueError, 'Duplicate'):
                predefined.read(s.native_body_bytes(damaged), 'Catalog')
        items[0][6][1] = s.atom('Renamed', True)
        self.image[self.owner + '.1c'] = s.native_body_bytes(docs)
        with self.assertRaisesRegex(ValueError, 'predefined value is missing'):
            references.resolve_values(self.xml, self.request)

    def test_invalid_counts_and_column_mappings_are_rejected(self):
        docs = s.Parser(self.image[self.owner + '.1c'].decode('utf-8-sig')).documents()
        for location in ('schema', 'mapping', 'children'):
            damaged = copy.deepcopy(docs); table = damaged[0][1]
            if location == 'schema':table[1][0] = s.atom(99)
            elif location == 'mapping':table[2][3] = table[2][5]
            else:table[2][16][2][-1][1] = s.atom(99)
            with self.subTest(location=location), self.assertRaises(ValueError):
                predefined.read(s.native_body_bytes(damaged), 'Catalog')

    def test_nested_catalog_items_share_the_same_identity_reader(self):
        docs = s.Parser(self.image[self.owner + '.1c'].decode('utf-8-sig')).documents()
        roots = docs[0][1][2][16][2][-1]
        first, second = roots[2:]
        first[4][1] = s.atom(1)
        first[-1] = s.atom(1)
        first.append([s.atom(1), s.atom(1), second])
        roots[1:] = [s.atom(1), first]
        self.assertEqual(set(predefined.read(s.native_body_bytes(docs), 'Catalog')), {'First', 'Second'})

    def test_current_version_storage_resolves_the_same_values_and_rejects_stale_streams(self):
        import metadata_context
        objects = metadata_context.context_objects(self.request['context'])
        docs = objects[self.owner]; a = s.atom; name = self.owner + '.1c'
        docs[0][11] = [a(1), a(name, True), a(s.ZERO)]
        metadata = s.text_bytes(docs); body = s.compress(self.image[self.owner]); stream = s.compress(self.image[name])
        digest = lambda value: a(hashlib.sha1(value).hexdigest(), True)
        storage = s.storage([metadata, body, stream], s.text_bytes([[a(0), a(1), a(self.owner),
            digest(metadata), digest(body), a(1), a(name, True), digest(stream)]]))
        context = s.storage([s.text_bytes(row) for row in objects.values()], s.text_bytes([[a(0)]]))
        request = dict(context=base64.b64encode(context).decode(), platform='8.5.1.1529')
        self.assertEqual(references.resolve_values(self.xml, request, storage), references.resolve_values(self.xml, self.request))
        docs[0][11][2] = a('99999999-9999-4999-8999-999999999999')
        request['context'] = base64.b64encode(s.storage([s.text_bytes(row) for row in objects.values()], s.text_bytes([[a(0)]]))).decode()
        with self.assertRaisesRegex(ValueError, 'external versions/context mismatch'):
            references.resolve_values(self.xml, request, storage)

    def test_predefined_reader_handles_chart_rowset_families(self):
        a = s.atom
        def identifier(value):return [a('#', True), a(ids.value_type_id('PredefinedIdentity')), [a(1), a(value)]]
        def string(value):return [a('S', True), a(value, True)]
        for kind, columns, values in [
            ('ChartOfCharacteristicTypes', [1, 2, 3], [identifier(self.owner), [a('B', True), a(0)], string('Entry')]),
            ('ChartOfAccounts', [0, 1], [identifier(self.owner), string('Entry')]),
            ('ChartOfCalculationTypes', [1, 2], [identifier(self.owner), string('Entry')]),
        ]:
            count = len(columns); schema = [a(count)] + [[a(column)] for column in columns]
            item = [a(2), a(1), a(count)] + values + [a(0)]
            if kind != 'ChartOfCalculationTypes':
                root_values = copy.deepcopy(values); root_values[0] = identifier(s.ZERO)
                synthetic = [a(2), a(0), a(count)] + root_values + [a(1), [a(1), a(1), item]]
                roots = [a(1), a(1), synthetic]
            else:roots = [a(1), a(1), item]
            rows = [a(2), a(count)]
            for offset, column in enumerate(columns):rows.extend([a(offset), a(column)])
            rows.append(roots)
            marker = predefined.FAMILIES[kind][0]
            body = [a(marker), schema, rows] if kind == 'ChartOfCalculationTypes' else [a(marker), [a(1), schema, rows, a(-1), a(1)]]
            with self.subTest(kind=kind):
                self.assertEqual(predefined.read(s.native_body_bytes([body]), kind), {'Entry': self.owner})


if __name__ == '__main__':
    unittest.main()
