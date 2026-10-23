"""Shared field conversion with independently exported native interfaces."""
import hashlib
import json
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as E

sys.path.insert(0, str(next((Path(__file__).resolve().parents[1] / 'src').rglob('managed_form_rules.py')).parent))
import native_metadata as s
import managed_form_xml as x
import managed_form_elements as elements
import managed_form_rules as rules
import v8unpack_backend as b


class NewFieldsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = Path(__file__).with_name('fixtures')
        cls.fixture = json.loads((folder / 'form_new_fields_851.json').read_text(encoding='utf-8'))
        base = json.loads((folder / 'form_rules_851.json').read_text(encoding='utf-8'))
        cls.paths = x.ObjectPaths({k: s.Parser(v).documents()[0] for k, v in {**base['paths'], **cls.fixture['paths']}.items()})
        cls.paths.types = {**base['types'], **cls.fixture['types']}
        cls.paths.tables = set(base['tables'])

    def convert(self, kind, xml, source=None):
        return x.convert(source or self.fixture['bases'][kind].encode('utf-8'), xml,
                         paths=self.paths, object_name='CRSAPI_FullCatalog')

    def entry(self, raw):
        form = x.interface(raw)
        index, _, _ = elements.form_collection(form)
        return form[1][index + 2]

    def baseline(self, kind):
        return next(c for c in self.fixture['cases'] if c['kind'] == kind and c['name'] == 'baseline')

    def test_complete_interfaces_match_39_native_samples(self):
        self.assertEqual(len(self.fixture['cases']), 39)
        for case in self.fixture['cases']:
            with self.subTest(kind=case['kind'], name=case['name'], value=case['value']):
                result = self.convert(case['kind'], case['xml'])
                signature = b.signature(s.Parser(result.decode('utf-8-sig')).documents())
                self.assertEqual(hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest(), case['sha256'])

    def test_create_all_new_field_kinds_from_an_empty_tree(self):
        for kind in self.fixture['bases']:
            form = x.interface(self.fixture['bases'][kind].encode('utf-8'))
            index, _, end = elements.form_collection(form)
            form[1][index] = s.atom(0)
            del form[1][index + 1:end]
            empty = b.assemble(b.to_model([form]))
            rebuilt = self.convert(kind, self.baseline(kind)['xml'], empty)
            with self.subTest(kind=kind):
                self.assertEqual(b.signature(x.interface(rebuilt)), b.signature(x.interface(self.fixture['bases'][kind].encode('utf-8'))))

    def test_removing_properties_restores_each_kind_defaults(self):
        for kind in self.fixture['bases']:
            root = E.fromstring(self.baseline(kind)['xml'])
            node = root.find('.//' + x.Q + kind)
            for case in self.fixture['cases']:
                if case['kind'] != kind or case['name'] not in rules.profiles()[kind]['properties']:
                    continue
                prop = node.find(x.Q + case['name'])
                if prop is None:
                    prop = E.SubElement(node, x.Q + case['name'])
                prop.text = case['value']
            changed = self.convert(kind, E.tostring(root, encoding='unicode'))
            restored = self.convert(kind, self.baseline(kind)['xml'], changed)
            self.assertEqual(b.signature(x.interface(restored)), b.signature(x.interface(self.fixture['bases'][kind].encode('utf-8'))))

    def test_calendar_and_progress_require_matching_binding_types(self):
        for kind in ('CalendarField', 'ProgressBarField'):
            root = E.fromstring(self.baseline(kind)['xml'])
            root.find('.//' + x.Q + kind + '/' + x.Q + 'DataPath').text = 'Object.Description'
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'requires'):
                self.convert(kind, E.tostring(root, encoding='unicode'))

    def test_removing_events_clears_all_field_event_vectors(self):
        for kind in ('RadioButtonField', 'CalendarField'):
            case = next(c for c in self.fixture['cases'] if c['kind'] == kind and c['name'] == 'events')
            changed = self.convert(kind, case['xml'])
            restored = self.entry(self.convert(kind, self.baseline(kind)['xml'], changed))
            for vector in rules.profiles()[kind]['events']:
                parent, slot = rules.location(restored, vector['path'], kind)
                self.assertEqual(s.render(parent[slot]), '{0,1,0}')

    def test_nested_field_move_and_deletion_preserve_full_conversion(self):
        kind = 'CalendarField'
        root = E.fromstring(self.baseline(kind)['xml'])
        items = root.find(x.Q + 'ChildItems')
        field = items[0]
        items.remove(field)
        group = E.SubElement(items, x.Q + 'UsualGroup', name='Container', id='900')
        E.SubElement(group, x.Q + 'Group').text = 'Vertical'
        children = E.SubElement(group, x.Q + 'ChildItems')
        children.append(field)
        first = self.convert(kind, E.tostring(root, encoding='unicode'))
        children.remove(field)
        items.append(field)
        moved = E.tostring(root, encoding='unicode')
        self.assertEqual(b.signature(x.interface(self.convert(kind, moved, first))), b.signature(x.interface(self.convert(kind, moved))))
        items.remove(field)
        removed = self.convert(kind, E.tostring(root, encoding='unicode'), first)
        self.assertNotIn('Probe', b.form_model(x.interface(removed))['elements']['data'])

    def test_ignored_radio_size_and_unmapped_special_properties_are_rejected(self):
        for kind, name, value in [('RadioButtonField', 'Width', '17'), ('ProgressBarField', 'MaxValue', '100'), ('CalendarField', 'SelectionMode', 'Single')]:
            root = E.fromstring(self.baseline(kind)['xml'])
            E.SubElement(root.find('.//' + x.Q + kind), x.Q + name).text = value
            with self.subTest(kind=kind, name=name), self.assertRaises(ValueError):
                self.convert(kind, E.tostring(root, encoding='unicode'))

    def test_demo_fields_identify_subtypes_with_optional_headers(self):
        fixture = json.loads((Path(__file__).with_name('fixtures') / 'form_demo_field_kinds_851.json').read_text(encoding='utf-8'))
        self.assertEqual(len(fixture['cases']), 7)
        for case in fixture['cases']:
            entry = s.Parser(case['native']).documents()[0]
            with self.subTest(kind=case['kind'], version=s.val(entry[0])):
                self.assertEqual(elements.native_kind(elements.FIELD_TYPE, entry, elements.layouts())[0], case['kind'])

    def test_optional_native_field_header_is_preserved_during_xml_edit(self):
        fixture = json.loads((Path(__file__).with_name('fixtures') / 'form_demo_field_kinds_851.json').read_text(encoding='utf-8'))
        native = s.Parser(next(c['native'] for c in fixture['cases'] if c['kind'] == 'CalendarField')).documents()[0]
        self.assertEqual(elements.field_header_size(native), 1)
        for kind in self.fixture['bases']:
            form = x.interface(self.fixture['bases'][kind].encode('utf-8'))
            index, _, _ = elements.form_collection(form)
            entry = form[1][index + 2]
            entry[4] = s.atom(1)
            entry.insert(5, native[5])
            source = b.assemble(b.to_model([form]))
            root = E.fromstring(self.baseline(kind)['xml'])
            E.SubElement(root.find('.//' + x.Q + kind), x.Q + 'Enabled').text = 'false'
            rebuilt = self.convert(kind, E.tostring(root, encoding='unicode'), source)
            expected = x.interface(source)
            expected[1][index + 2][14] = s.atom(0)
            with self.subTest(kind=kind):
                self.assertEqual(b.signature(x.interface(rebuilt)), b.signature(expected))

    def test_invalid_optional_field_headers_are_rejected(self):
        entry = self.entry(self.fixture['bases']['CalendarField'].encode('utf-8'))
        entry[4] = s.atom(999)
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            elements.native_kind(elements.FIELD_TYPE, entry, elements.layouts())


if __name__ == '__main__':
    unittest.main()
