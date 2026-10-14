"""Complete table XML properties compared with native 8.5.1 interfaces."""
import hashlib
import json
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as E

sys.path.insert(0, str(next((Path(__file__).resolve().parents[1] / 'src').rglob('managed_form_rules.py')).parent))
import metadata_serializer as s
import managed_form_xml as x
import v8unpack_backend as b
import managed_form_elements as elements
import managed_form_rules as rules


class TableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = Path(__file__).with_name('fixtures')
        cls.fixture = json.loads((folder / 'form_table_rules_851.json').read_text(encoding='utf-8'))
        base = json.loads((folder / 'form_rules_851.json').read_text(encoding='utf-8'))
        cls.paths = x.ObjectPaths({k: s.Parser(v).documents()[0] for k, v in base['paths'].items()})
        cls.paths.types = base['types']
        cls.paths.tables = set(base['tables'])

    def convert(self, xml, source=None):
        return x.convert(source or self.fixture['bases']['Table'].encode('utf-8'), xml,
                         paths=self.paths, object_name='CRSAPI_FullCatalog')

    def test_complete_interfaces_match_19_native_samples(self):
        self.assertEqual(len(self.fixture['cases']), 19)
        for case in self.fixture['cases']:
            with self.subTest(name=case['name'], value=case['value']):
                result = self.convert(case['xml'])
                signature = b.signature(s.Parser(result.decode('utf-8-sig')).documents())
                self.assertEqual(hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest(), case['sha256'])

    def test_full_xml_removal_restores_all_table_defaults(self):
        baseline = self.fixture['cases'][0]['xml']
        root = E.fromstring(baseline)
        table = root.find('.//' + x.Q + 'Table')
        for case in self.fixture['cases'][1:]:
            if table.find(x.Q + case['name']) is None:
                E.SubElement(table, x.Q + case['name']).text = case['value']
        changed = self.convert(E.tostring(root, encoding='unicode'))
        restored = self.convert(baseline, changed)
        self.assertEqual(b.signature(x.interface(restored)), b.signature(x.interface(self.fixture['bases']['Table'].encode('utf-8'))))

    def test_table_properties_survive_column_and_event_changes(self):
        root = E.fromstring(self.fixture['cases'][0]['xml'])
        table = root.find('.//' + x.Q + 'Table')
        for name, value in [('Header', 'false'), ('Footer', 'true'), ('HorizontalLines', 'false'), ('UseAlternationRowColor', 'true')]:
            E.SubElement(table, x.Q + name).text = value
        column = E.SubElement(table.find(x.Q + 'ChildItems'), x.Q + 'InputField', name='TextColumn', id='120')
        E.SubElement(column, x.Q + 'DataPath').text = 'Object.Rows.Text'
        events = E.SubElement(table, x.Q + 'Events')
        E.SubElement(events, x.Q + 'Event', name='Selection').text = 'SelectRow'
        xml = E.tostring(root, encoding='unicode')
        first = self.convert(xml)
        self.assertEqual(b.signature(x.interface(first)), b.signature(x.interface(self.convert(xml, first))))
        table.find(x.Q + 'ChildItems').remove(column)
        table.remove(events)
        smaller = E.tostring(root, encoding='unicode')
        entries = []
        for result in (self.convert(smaller, first), self.convert(smaller)):
            form = x.interface(result)
            index, _, _ = elements.form_collection(form)
            entry = form[1][index + 2]
            self.assertEqual(s.val(entry[elements.table_children(entry)]), '0')
            entries.append(entry)
        # Native event service headers remain materialized after removing events.
        # Compare property slots through their dynamic paths instead of headers.
        for name in ('Header', 'Footer', 'HorizontalLines', 'UseAlternationRowColor'):
            for default in rules.profiles()['Table']['properties'][name]['defaults']:
                values = []
                for entry in entries:
                    parent, slot = rules.location(entry, default['path'], 'Table')
                    values.append(s.render(parent[slot]))
                self.assertEqual(*values)

    def test_unknown_tristate_and_negative_height_are_rejected(self):
        for name, value in [('HorizontalLines', 'Auto'), ('HeightInTableRows', '-1')]:
            root = E.fromstring(self.fixture['cases'][0]['xml'])
            E.SubElement(root.find('.//' + x.Q + 'Table'), x.Q + name).text = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.convert(E.tostring(root, encoding='unicode'))


if __name__ == '__main__':
    unittest.main()
