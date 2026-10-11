"""Replacement source streams without modifying CommonModule properties."""
import base64
import hashlib
import unittest
import uuid
import test_constant_serializer as const
import metadata_serializer as s
import constant_serializer as c
import commonmodule_serializer as module
import test_commonmodule_serializer as create


def fixture():
    created = c.serialize(create.fixture())
    _, objects = create.contents(created)
    docs, data, external = objects[const.CID]
    m = docs[0]
    m[0], m[5], m[6] = s.atom(5), s.atom(9), s.atom(9)
    original = base64.b64decode(s.val(m[7])).hex()
    for index in (7, 8):
        m[index] = s.atom(str(uuid.UUID(bytes_le=base64.b64decode(s.val(m[index]))[:16])))
    m[11][2] = s.atom(str(uuid.UUID(bytes_le=base64.b64decode(s.val(m[11][2]))[:16])))
    docs[2] = [s.atom(0)]
    meta = s.text_bytes(docs)
    manifest = s.text_bytes([[s.atom(0), s.atom(1), s.atom(const.CID),
        s.atom(hashlib.sha1(meta).hexdigest(), True), s.atom(hashlib.sha1(data).hexdigest(), True), s.atom(0)]])
    snapshot = s.storage([meta, data], manifest)
    docs[2] = [s.atom(1), [m[11][1], m[11][2], s.atom(1)]]
    return dict(platform='8.5.1.1529', object_id=const.CID, original_version=original,
        snapshot=base64.b64encode(snapshot).decode(),
        context=base64.b64encode(s.storage([s.text_bytes(docs)], s.text_bytes([[s.atom(0)]]))).decode(),
        source_text='Function Value() Export\n Return "Изменено";\nEndFunction\n')


class CommonModuleChangeTests(unittest.TestCase):
    def test_source_changes_body_and_descriptors_are_preserved(self):
        request = fixture(); result = module.serialize_change(request)
        _, pos = s.read_record(base64.b64decode(request['snapshot']), 12)
        previous_body, _ = s.read_record(base64.b64decode(request['snapshot']), pos)
        raw = s.inflate(base64.b64decode(result['data'])[18:])
        graph, pos = s.read_record(raw, 0); storage, end = s.read_record(raw, pos + 4)
        s.validate_storage(storage)
        meta, pos = s.read_record(storage, 12)
        body, pos = s.read_record(storage, pos)
        external, pos = s.read_record(storage, pos)
        docs = s.Parser(meta.decode('utf-8-sig')).documents()
        self.assertEqual(body, previous_body)
        self.assertEqual(s.val(docs[0][9]), 'XML_Module')
        self.assertEqual(result['original'], request['original_version'])
        self.assertNotEqual(result['local'], result['original'])
        self.assertEqual(base64.b64decode(s.val(docs[0][11][2])).hex(), result['external_version'])
        self.assertEqual(create.container_members(s.inflate(external))['text'].decode('utf-8-sig'), request['source_text'].replace('\n', '\r\n'))
        self.assertIn(s.render(docs[0][11]), graph.decode('utf-8-sig'))

    def test_version_context_class_and_stream_guards(self):
        r = fixture()
        for field, value in (('original_version', 'f' * 40), ('platform', '8.5.4.1878'),
                             ('object_id', str(uuid.uuid4())), ('source_text', '\0')):
            bad = dict(r); bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): module.serialize_change(bad)
        for mutate in ('class', 'stream', 'children', 'external-context'):
            docs = s.context_metadata(base64.b64decode(r['context']), const.CID)
            if mutate == 'class': docs[0][2] = s.atom(c.CLASS)
            if mutate == 'stream': docs[0][11][1] = s.atom('other.0', True)
            if mutate == 'children': docs[0][12] = [s.atom(1)]
            if mutate == 'external-context': docs[2][1][0] = s.atom('other.0', True)
            bad = dict(r, context=base64.b64encode(s.storage([s.text_bytes(docs)], s.text_bytes([[s.atom(0)]]))).decode())
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): module.serialize_change(bad)


if __name__ == '__main__': unittest.main()
