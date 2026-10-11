"""Offline protocol checks; synthetic objects contain no repository credentials."""
import base64
import copy
import hashlib
from pathlib import Path
import struct
import sys
import unittest
import uuid
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'Сериализация'))
import comment_serializer as s

ID = 'e2a9c158-4b91-424a-b10d-07b43280ce83'
VERSION = '30e59a31-bafa-4035-a368-705c1330444a'
CHILD = '0e108dde-b410-4f8a-988b-3e90ae5210cb'
CHILD_CLASS = '9cd510ce-abfc-11d4-9434-004095e12fc7'


def xml(comment, name='Конфигурация'):
    root = ET.Element('MetaDataObject', xmlns='http://v8.1c.ru/8.3/MDClasses')
    props = ET.SubElement(ET.SubElement(root, 'Configuration', uuid=ID), 'Properties')
    ET.SubElement(props, 'Name').text = name
    ET.SubElement(props, 'Comment').text = comment
    ET.SubElement(props, 'Vendor').text = 'Тест'
    return ET.tostring(root, encoding='unicode')


def fixture():
    metadata = ('{5,%s,%s,%s,%s,5,5,%s,%s,"Конфигурация",0,{0},'
                '{1,{%s,1,%s}},{1,%s},{1,%s,0},"Конфигурация",0},'
                '{4294967295,0,%s,00010101000000},{0}') % (
                    ID, s.ROOT_CLASS, s.ZERO, s.ZERO, VERSION, VERSION,
                    CHILD_CLASS, CHILD, s.BASIC_FEATURE, CHILD, s.ZERO)
    meta = b'\xef\xbb\xbf' + metadata.encode('utf-8')
    content = ('{2,{%s},7,{4,{1,0,%s},"Конфигурация",{0},"До",0},'
               '{1,%s},"посторонняя строка: До"}') % (ID, s.BASIC_FEATURE, CHILD)
    raw = b'\xef\xbb\xbf' + content.encode('utf-8')
    compressed = s.compress(raw)
    manifest = s.text_bytes([[s.atom(0), s.atom(1), s.atom(ID),
                             s.atom(hashlib.sha1(meta).hexdigest(), True),
                             s.atom(hashlib.sha1(compressed).hexdigest(), True), s.atom(0)]])
    snapshot = s.storage([meta, compressed], manifest)
    context = s.storage([meta], s.text_bytes([[s.atom(0), s.atom(1), s.atom(ID)]]))
    request = dict(platform='8.5.4.1878', repository='Test', repository_version=VERSION,
                   object_id=ID, original_version=uuid.UUID(VERSION).bytes_le.hex() + '00000000',
                   snapshot=base64.b64encode(snapshot).decode(), context=base64.b64encode(context).decode(),
                   before_xml=xml('До'), after_xml=xml('После'))
    return request, raw


def property_fixture():
    request, raw = fixture()
    docs = s.Parser(raw.decode('utf-8-sig')).documents()
    common = s.common_properties(docs, ID)
    props = [s.atom(0) for _ in range(81)]
    props[0] = s.atom(79)
    props[1] = [s.atom(0), copy.deepcopy(common)]
    for key, slot in s.PROPERTY_SLOTS.items():
        props[slot] = s.atom('Тест' if key == 'Vendor' else '', True)
    docs[0][3:] = [[s.atom(s.ROOT_FEATURE_CLASS), [s.atom(1), props]], [s.atom(1), s.atom(CHILD)], s.atom('До', True)]
    raw = s.text_bytes(docs)
    metadata, _ = s.read_record(base64.b64decode(request['snapshot']), 12)
    data = s.compress(raw)
    manifest = s.text_bytes([[s.atom(0), s.atom(1), s.atom(ID),
                             s.atom(hashlib.sha1(metadata).hexdigest(), True),
                             s.atom(hashlib.sha1(data).hexdigest(), True), s.atom(0)]])
    request['snapshot'] = base64.b64encode(s.storage([metadata, data], manifest)).decode()
    before = ET.fromstring(xml('До'))
    for node in before.iter():
        node.tag = node.tag.rsplit('}', 1)[-1]
    xmlprops = before.find('.//Properties')
    ET.SubElement(xmlprops, 'Synonym')
    for key in s.PROPERTY_SLOTS:
        if key != 'Vendor':
            ET.SubElement(xmlprops, key)
    request['mode'] = 'properties'
    request['before_xml'] = ET.tostring(before, encoding='unicode')
    request['after_xml'] = request['before_xml']
    return request, raw


class SerializerTests(unittest.TestCase):
    def test_string_properties_individually_and_together(self):
        for keys in [(key,) for key in s.PROPERTY_SLOTS] + [tuple(s.PROPERTY_SLOTS) + ('Comment',)]:
            request, original = property_fixture()
            changed = ET.fromstring(request['after_xml'])
            for key in keys:
                changed.find('.//Properties/' + key).text = 'Значение "' + key + '" & текст\nстрока'
            request['after_xml'] = ET.tostring(changed, encoding='unicode')
            _, raw = s.serialize(request)
            olddocs = s.Parser(original.decode('utf-8-sig')).documents()
            newdocs = s.Parser(raw.decode('utf-8-sig')).documents()
            props = s.configuration_properties(newdocs)
            common = s.common_properties(newdocs, ID)
            for key in keys:
                token = common[4] if key == 'Comment' else props[s.PROPERTY_SLOTS[key]]
                self.assertEqual(s.val(token), changed.find('.//Properties/' + key).text)
            # Reverse only the changed properties; all other bytes must remain identical.
            text = raw.decode('utf-8-sig')
            reverse = []
            for key in keys:
                new = common[4] if key == 'Comment' else props[s.PROPERTY_SLOTS[key]]
                old = s.common_properties(olddocs, ID)[4] if key == 'Comment' else s.configuration_properties(olddocs)[s.PROPERTY_SLOTS[key]]
                reverse.append((new.start, new.end, s.render(old)))
            for start, end, value in sorted(reverse, reverse=True):
                text = text[:start] + value + text[end:]
            self.assertEqual(text, original.decode('utf-8-sig'))

    def test_synonym_creation_edit_and_removal(self):
        request, _ = property_fixture()
        pairs = [('ru', 'Синоним "русский"'), ('en', 'English & text')]
        changed = ET.fromstring(request['after_xml'])
        synonym = changed.find('.//Properties/Synonym')
        for lang, content in pairs:
            item = ET.SubElement(synonym, '{http://v8.1c.ru/8.1/data/core}item')
            ET.SubElement(item, '{http://v8.1c.ru/8.1/data/core}lang').text = lang
            ET.SubElement(item, '{http://v8.1c.ru/8.1/data/core}content').text = content
        request['after_xml'] = ET.tostring(changed, encoding='unicode')
        _, raw = s.serialize(request)
        docs = s.Parser(raw.decode('utf-8-sig')).documents()
        token = s.common_properties(docs, ID)[3]
        self.assertEqual(s.synonym_value(token), pairs)
        # Check nonempty -> empty and nonempty -> edited, without replacing other bytes.
        for replacement in ([], [('ru', 'Новый')]):
            current = s.xml_property_patches(request['after_xml'], request['before_xml'], ID, s.common_properties(docs, ID), docs)
            self.assertEqual(current, [(token.start, token.end, '{0}')])
            if replacement:
                synonym[0].find('{http://v8.1c.ru/8.1/data/core}content').text = 'Новый'
                synonym.remove(synonym[1])
                patches = s.xml_property_patches(request['after_xml'], ET.tostring(changed, encoding='unicode'), ID,
                                                  s.common_properties(docs, ID), docs)
                self.assertEqual(patches[0][2], '{1,"ru","Новый"}')

    def test_properties_reject_stale_values_and_unknown_changes(self):
        original, _ = property_fixture()
        for mutation in ('baseline', 'unsupported', 'duplicate', 'attributes', 'name'):
            request = copy.deepcopy(original)
            before, after = ET.fromstring(request['before_xml']), ET.fromstring(request['after_xml'])
            after.find('.//Vendor').text = 'Изменение'
            if mutation == 'baseline':
                before.find('.//Vendor').text = 'Устарел'
            elif mutation == 'unsupported':
                ET.SubElement(after.find('.//Properties'), 'DefaultRunMode').text = 'OrdinaryApplication'
            elif mutation == 'duplicate':
                ET.SubElement(after.find('.//Properties'), 'Vendor').text = 'Дубликат'
            elif mutation == 'attributes':
                after.find('.//Vendor').set('unexpected', 'true')
            else:
                after.find('.//Name').text = 'Переименовано'
            request['before_xml'], request['after_xml'] = ET.tostring(before, encoding='unicode'), ET.tostring(after, encoding='unicode')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                s.serialize(request)

    def test_invalid_synonyms_and_unknown_native_layout(self):
        request, raw = property_fixture()
        after = ET.fromstring(request['after_xml'])
        synonym = after.find('.//Synonym')
        for _ in range(2):
            item = ET.SubElement(synonym, '{http://v8.1c.ru/8.1/data/core}item')
            ET.SubElement(item, '{http://v8.1c.ru/8.1/data/core}lang').text = 'ru'
            ET.SubElement(item, '{http://v8.1c.ru/8.1/data/core}content').text = 'Дубликат'
        request['after_xml'] = ET.tostring(after, encoding='unicode')
        with self.assertRaisesRegex(ValueError, 'Duplicate XML Synonym'):
            s.serialize(request)
        docs = s.Parser(raw.decode('utf-8-sig')).documents()
        docs[0][3][1][1][0] = s.atom(78)
        with self.assertRaisesRegex(ValueError, 'property layout'):
            s.configuration_properties(docs)
        request['mode'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'serialization mode'):
            s.serialize(request)

    def test_comment_roundtrip_preserves_other_bytes_and_graph(self):
        request, original = fixture()
        for comment in ('', 'Кириллица "кавычки" & XML\nстрока', '{1,2}', 'До\tпосле'):
            with self.subTest(comment=comment):
                request['after_xml'] = xml(comment)
                packet, raw = s.serialize(request)
                old_text = original.decode('utf-8-sig')
                old = s.common_properties(s.Parser(old_text).documents(), ID)[4]
                expected = old_text[:old.start] + s.render(s.atom(comment, True)) + old_text[old.end:]
                self.assertEqual(raw, b'\xef\xbb\xbf' + expected.encode('utf-8'))
                self.assertEqual(s.val(s.common_properties(s.Parser(raw.decode('utf-8-sig')).documents(), ID)[4]), comment)
                root = ET.fromstring(packet)
                self.assertIsNone(root.find('{%s}auth' % s.NS))
                binary = base64.b64decode(root.find('.//{%s}data' % s.NS).text)
                self.assertEqual(binary[:18], s.SERIALIZER)
                transport = s.inflate(binary[18:])
                graph, pos = s.read_record(transport, 0)
                self.assertIn(CHILD.encode(), graph)
                self.assertIn(CHILD_CLASS.encode(), graph)
                self.assertEqual(transport[pos:pos + 4], bytes(4))
                snapshot, end = s.read_record(transport, pos + 4)
                self.assertEqual(end, len(transport))
                s.validate_storage(snapshot)
                meta, p = s.read_record(snapshot, 12)
                data, p = s.read_record(snapshot, p)
                self.assertEqual(s.inflate(data), raw)
                self.assertTrue(meta.startswith(b'\xef\xbb\xbf{6,'))

    def test_unsupported_xml_and_stale_baseline(self):
        request, _ = fixture()
        cases = [xml('До'), xml('После', name='ДругоеИмя'), xml('После').replace('Тест', 'Другой'),
                 xml('После').replace(ID, s.ZERO), '<!DOCTYPE x>' + xml('После'),
                 xml('После').replace('</Properties>', '<Comment>Дубликат</Comment></Properties>')]
        for changed in cases:
            with self.subTest(xml=changed):
                request['after_xml'] = changed
                with self.assertRaises(ValueError):
                    s.serialize(request)
        request, _ = fixture()
        request['before_xml'] = xml('Устаревший')
        with self.assertRaisesRegex(ValueError, 'Baseline'):
            s.serialize(request)

    def test_versions_and_platform(self):
        original, _ = fixture()
        for key, value in [('platform', '8.3.27.2342'), ('object_id', s.ZERO),
                           ('original_version', '00' * 20), ('repository_version', 'invalid')]:
            with self.subTest(key=key):
                request = copy.deepcopy(original)
                request[key] = value
                with self.assertRaises(ValueError):
                    s.serialize(request)

    def test_context_version_mismatch_and_unsupported_object(self):
        original, _ = fixture()
        metadata, _ = s.read_record(base64.b64decode(original['context']), 12)
        for changed in (metadata.replace(b',5,5,', b',4,4,'),
                        metadata.replace(s.ROOT_CLASS.encode(), CHILD_CLASS.encode()),
                        metadata.replace(b'{0},{1,{', b'{1},{1,{', 1)):
            request = copy.deepcopy(original)
            context = s.storage([changed], s.text_bytes([[s.atom(0)]]))
            request['context'] = base64.b64encode(context).decode()
            with self.assertRaises(ValueError):
                s.serialize(request)

    def test_ambiguous_common_properties_are_rejected(self):
        _, raw = fixture()
        docs = s.Parser(raw.decode('utf-8-sig')).documents()
        common = s.common_properties(docs, ID)
        docs[0].append(copy.deepcopy(common))
        with self.assertRaisesRegex(ValueError, 'common properties'):
            s.common_properties(docs, ID)

    def test_storage_corruption_and_truncation(self):
        request, _ = fixture()
        for key in ('snapshot', 'context'):
            original = base64.b64decode(request[key])
            for pos in (0, 24, len(original) - 65, len(original) - 1):
                damaged = bytearray(original)
                damaged[pos] ^= 1
                with self.subTest(key=key, pos=pos), self.assertRaises(ValueError):
                    s.validate_storage(damaged)
            with self.assertRaises(ValueError):
                s.validate_storage(original[:-1])
            # A correct outer checksum must not hide corruption in the index.
            damaged = bytearray(original)
            index = len(damaged) - struct.unpack_from('<Q', damaged, len(damaged) - 64)[0]
            damaged[index + 22] ^= 1
            damaged[-20:] = hashlib.sha1(damaged[:-20]).digest()
            with self.assertRaisesRegex(ValueError, 'index checksum'):
                s.validate_storage(damaged)

    def test_invalid_compression_and_serialization(self):
        compressed = s.compress(b'content')
        for data in (compressed[:-1], compressed + b'extra'):
            with self.assertRaises(ValueError):
                s.inflate(data)
        for text in ('{1', '{"unclosed}', '{1} garbage', '{' * 130):
            with self.assertRaises(ValueError):
                s.Parser(text).documents()


if __name__ == '__main__':
    unittest.main()
