"""Native CommonModule bodies, external text and preservation regressions."""
import base64
import hashlib
import struct
import unittest
import uuid
import test_enum_serializer as enum
import test_object_creation_serializer as const
import commonmodule_serializer as module
import metadata_identifiers
import xml_namespaces
import object_creation_serializer as c
import native_metadata as s


def xml():
    return ('<MetaDataObject xmlns="%s" version="2.21"><CommonModule uuid="%s">'
            '<Properties><Name>XML_Module</Name><Server>true</Server></Properties>'
            '</CommonModule></MetaDataObject>') % (xml_namespaces.MD, const.CID)


def fixture():
    r = enum.fixture()
    rid = r['object_id']
    raw = base64.b64decode(r['snapshots'][rid])
    meta, pos = s.read_record(raw, 12)
    data, pos = s.read_record(raw, pos)
    docs = s.Parser(s.inflate(data).decode('utf-8-sig')).documents()
    docs[0].append([s.atom(metadata_identifiers.class_id('CommonModule')), s.atom(0)])
    data = s.compress(s.text_bytes(docs))
    manifest = s.text_bytes([[s.atom(0), s.atom(1), s.atom(rid),
        s.atom(hashlib.sha1(meta).hexdigest(), True), s.atom(hashlib.sha1(data).hexdigest(), True), s.atom(0)]])
    r['snapshots'][rid] = base64.b64encode(s.storage([meta, data], manifest)).decode()
    r.update(object_type='CommonModule', object_xml=xml(), source_text='Function Value() Export\n Return "Тест";\nEndFunction\n')
    return r


def contents(result):
    raw = s.inflate(base64.b64decode(result['data'])[18:])
    graph, pos = s.read_record(raw, 0)
    storage, end = s.read_record(raw, pos + 4)
    s.validate_storage(storage)
    pos = 12
    objects = {}
    for _ in result['descriptions']:
        meta, pos = s.read_record(storage, pos)
        body, pos = s.read_record(storage, pos)
        docs = s.Parser(meta.decode('utf-8-sig')).documents()
        external = []
        for _ in docs[2][1:]:
            data, pos = s.read_record(storage, pos)
            external.append(data)
        objects[s.val(docs[0][1])] = (docs, body, external)
    return s.Parser(graph.decode('utf-8-sig')).documents()[0], objects


def container_members(raw):
    def block(pos):
        size = int(raw[pos + 2:pos + 10], 16)
        return raw[pos + 31:pos + 31 + size]
    table = block(16)
    result = {}
    for pos in range(0, len(table), 12):
        attr, data, marker = struct.unpack_from('<III', table, pos)
        name = block(attr)[20:-4].decode('utf-16le')
        result[name] = block(data)
    return result


class CommonModuleTests(unittest.TestCase):
    def test_body_properties_and_strict_layout(self):
        oid, name, body, ids = module.module_xml(xml())
        doc = s.Parser(body.decode('utf-8-sig')).documents()[0]
        self.assertEqual((oid, name, ids), (const.CID, 'XML_Module', []))
        self.assertEqual(s.val(doc[1][1][1][2]), const.CID)
        self.assertEqual(s.val(doc[1][3]), '1')
        without_server=s.Parser(module.module_xml(xml().replace('true','false'))[2].decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.val(without_server[1][3]),'0')
        global_module=s.Parser(module.module_xml(xml().replace('<Server>true</Server>','<Global>true</Global>'))[2].decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.val(global_module[1][6]),'1')
        for text in (xml().replace('true','unknown'), xml().replace('</Properties>','<Server>false</Server></Properties>'), xml().replace('</Properties>', '<Unknown/></Properties>')):
            with self.assertRaises(ValueError): module.module_xml(text)
        with self.assertRaises(ValueError): module.module_xml(xml(), '8.5.4.1878')

    def test_source_container(self):
        raw = module.module_container('\ufeff// Тест\nReturn "x";\r\n')
        files = container_members(raw)
        self.assertEqual(files['info'], b'\xef\xbb\xbf{3,1,0,"",0}')
        self.assertEqual(files['text'].decode('utf-8-sig'), '// Тест\r\nReturn "x";\r\n')
        self.assertEqual(container_members(module.module_container(''))['text'], b'\xef\xbb\xbf')
        for text in (None, '\0', 'x' * (8 * 1024 * 1024)):
            with self.assertRaises(ValueError): module.module_container(text)

    def test_external_graph_and_storage(self):
        r = fixture(); result = c.serialize(r)
        graph, objects = contents(result)
        docs, body, external = objects[const.CID]
        self.assertEqual(s.val(docs[0][11][1]), const.CID + '.0')
        self.assertEqual(s.val(docs[2][1][2]), '1')
        self.assertEqual(len(external), 1)
        self.assertEqual(container_members(s.inflate(external[0]))['text'].decode('utf-8-sig'), r['source_text'].replace('\n', '\r\n'))
        self.assertEqual(result['externals'][0]['action'], 1)
        self.assertIn(s.render(docs[0][11]), s.render(graph[7]))

    def test_existing_external_version_is_preserved(self):
        r = fixture(); first = c.serialize(r); _, objects = contents(first)
        snapshots = {}; records = []
        for oid, (docs, body, external) in objects.items():
            m = docs[0]; m[0] = s.atom(5); m[5] = m[6] = s.atom(1)
            for i in (7, 8): m[i] = s.atom(str(uuid.UUID(bytes_le=base64.b64decode(s.val(m[i]))[:16])))
            if len(m[11]) > 1:
                m[11][2] = s.atom(str(uuid.UUID(bytes_le=base64.b64decode(s.val(m[11][2]))[:16])))
            docs[2] = [s.atom(0)]
            meta = s.text_bytes(docs)
            if len(m[11]) > 1:
                docs[2] = [s.atom(1), [m[11][1], m[11][2], s.atom(1)]]
            records.append(s.text_bytes(docs))
            manifest = s.text_bytes([[s.atom(0), s.atom(1), s.atom(oid), s.atom(hashlib.sha1(meta).hexdigest(), True), s.atom(hashlib.sha1(body).hexdigest(), True), s.atom(0)]])
            snapshots[oid] = base64.b64encode(s.storage([meta, body], manifest)).decode()
        r.update(context=base64.b64encode(s.storage(records, s.text_bytes([[s.atom(0)]]))).decode(), snapshots=snapshots,
                 object_xml=xml().replace(const.CID, 'dddddddd-dddd-4ddd-8ddd-dddddddddddd').replace('XML_Module', 'Next_Module'))
        second = c.serialize(r); _, objects = contents(second)
        previous = next(v for v in second['externals'] if v['object_id'] == const.CID)
        self.assertEqual(previous['action'], 0)
        self.assertEqual(previous['version'], first['externals'][0]['version'])
        self.assertEqual(objects[const.CID][2], [])


if __name__ == '__main__': unittest.main()
