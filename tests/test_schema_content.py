"""Compare complete schema XML parts against independent native CF exports."""
import hashlib
import json
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(next((Path(__file__).resolve().parents[1] / 'src').rglob('schema_content.py')).parent))
import schema_content as schemas


def signature(node):
    attrs = []
    for attr in node.attributes.values():
        if attr.namespaceURI == schemas.XMLNS:
            continue
        value = attr.value
        if (attr.namespaceURI, attr.localName) == (schemas.XSI, 'type'):
            value = schemas._qname(node, value)
        attrs.append(((attr.namespaceURI, attr.localName), value))
    children = []
    elements = schemas._elements(node)
    for child in elements:
        text = ''.join(n.data for n in child.childNodes if n.nodeType == n.TEXT_NODE)
        # Different native saves materialize these optional empty defaults.
        significant_attrs = [a for a in child.attributes.values() if a.namespaceURI != schemas.XMLNS]
        if child.localName in ('appearance', 'inputParameters', 'outputParameters') and \
                not schemas._elements(child) and not text.strip() and not significant_attrs:
            continue
        children.append(signature(child))
    text = ''.join(n.data for n in node.childNodes if n.nodeType in (n.TEXT_NODE, n.CDATA_SECTION_NODE))
    return ((node.namespaceURI, node.localName), sorted(attrs, key=str),
            None if elements and not text.strip() else text, children)


def digest(raw):
    data = signature(schemas._parse(raw).documentElement)
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


class SchemaContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(Path(__file__).with_name('fixtures').joinpath('schema_content_851.json').read_text(encoding='utf-8'))['cases']

    def test_complete_native_schema_parts(self):
        for case in self.cases:
            with self.subTest(schema=case['object_id']):
                raw = schemas.convert(case['xml'], case['type_ids'], case['style_ids'])
                self.assertEqual([digest(part) for part in schemas.unpack(raw)], case['parts'])

    def test_generated_type_requires_current_uuid(self):
        case = next(case for case in self.cases if case['type_ids'])
        with self.assertRaisesRegex(ValueError, 'Missing generated schema type UUID'):
            schemas.convert(case['xml'], style_ids=case['style_ids'])

    def test_style_requires_current_uuid_and_not_a_specific_prefix(self):
        case = next(case for case in self.cases if case['style_ids'])
        with self.assertRaisesRegex(ValueError, 'Missing schema style UUID'):
            schemas.convert(case['xml'], case['type_ids'])
        renamed = case['xml'].replace('xmlns:style=', 'xmlns:sty="http://v8.1c.ru/8.1/data/ui/style" xmlns:style=').replace('>style:', '>sty:')
        raw = schemas.convert(renamed, case['type_ids'], case['style_ids'])
        self.assertEqual([digest(part) for part in schemas.unpack(raw)], case['parts'])

    def test_unsupported_picture_fails_before_packaging(self):
        case = next(case for case in self.cases if 'AppearanceCircleRed' in case['xml'])
        xml = case['xml'].replace('StdPicture.AppearanceCircleRed', 'StdPicture.UnknownPicture')
        with self.assertRaisesRegex(ValueError, 'Unverified schema picture'):
            schemas.convert(xml, case['type_ids'], case['style_ids'])

    def test_dtd_and_invalid_variant_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'DTD'):
            schemas.convert('<!DOCTYPE x [<!ENTITY a "text">]><x/>')
        xml = '<DataCompositionSchema xmlns="%s"><settingsVariant/></DataCompositionSchema>' % schemas.SCHEMA
        with self.assertRaisesRegex(ValueError, 'one settings'):
            schemas.convert(xml)

    def test_truncated_streams_are_rejected(self):
        case = self.cases[0]
        raw = schemas.convert(case['xml'], case['type_ids'], case['style_ids'])
        parts = schemas.unpack(raw)
        for broken in (raw[:12], raw[:-len(parts[-1])], struct.pack('<IIQ', 0, 0, 2**63)):
            with self.subTest(size=len(broken)), self.assertRaises(ValueError):
                schemas.unpack(broken)


if __name__ == '__main__':
    unittest.main()
