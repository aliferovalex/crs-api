"""CommonModule properties and its native info/text external container."""
import base64
import copy
import hashlib
import json
import re
import struct
import sys
import uuid
import zlib
import metadata_serializer as s
import metadata_identifiers as identifiers
import platform_profiles as platforms


def module_xml(text, platform='8.5.1.1529'):
    from flat_object_serializer import object_xml
    return object_xml(text, platform, 'CommonModule')


def module_container(source):
    if not isinstance(source, str) or '\0' in source:
        raise ValueError('Invalid module source text')
    source = source.removeprefix('\ufeff').replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')
    encoded = b'\xef\xbb\xbf' + source.encode('utf-8')
    if len(encoded) > 8 * 1024 * 1024:
        raise ValueError('Oversized module source text')
    files = [('info', b'\xef\xbb\xbf{3,1,0,"",0}'), ('text', encoded)]
    marker = 0x7fffffff

    def block(data, minimum=0):
        size = max(len(data), minimum)
        return ('\r\n%08x %08x %08x \r\n' % (len(data), size, marker)).encode('ascii') + data + bytes(size - len(data))

    # 16-byte header, 31-byte table block header, two 12-byte entries.
    content = bytearray(struct.pack('<IIII', marker, 512, 2, 0) + bytes(31 + 24))
    entries = []
    for name, data in files:
        attribute = bytes(20) + name.encode('utf-16le') + bytes(4)
        attr_pos = len(content)
        content += block(attribute)
        data_pos = len(content)
        content += block(data, 512)
        entries.append(struct.pack('<III', attr_pos, data_pos, marker))
    content[16:71] = block(b''.join(entries))
    return bytes(content)


def serialize_change(request):
    """Replace the sole external source stream of an existing CommonModule."""
    if not platforms.legacy(request['platform']):
        raise ValueError('CommonModule changes require legacy platform profile')
    oid = str(uuid.UUID(request['object_id']))
    for key in ('snapshot', 'context'):
        if not isinstance(request[key], str) or len(request[key]) > s.MAX_BYTES * 2:
            raise ValueError('Oversized or invalid module input')
    snapshot = base64.b64decode(request['snapshot'], validate=True)
    context = base64.b64decode(request['context'], validate=True)
    s.validate_storage(snapshot); s.validate_storage(context)
    metadata, pos = s.read_record(snapshot, 12)
    data, pos = s.read_record(snapshot, pos)
    saved = s.Parser(metadata.decode('utf-8-sig')).documents()
    docs = s.context_metadata(context, oid)
    if len(docs) != 3 or len(saved) != 3 or len(docs[0]) != 17 or len(saved[0]) != 17:
        raise ValueError('Unsupported module metadata')
    m = docs[0]
    if (s.val(m[0]) != '5' or s.val(saved[0][0]) != '5'
            or [s.render(v) for v in m[:12]] != [s.render(v) for v in saved[0][:12]]):
        raise ValueError('Module snapshot/context mismatch')
    if (s.val(m[1]) != oid or s.val(m[2]) != identifiers.class_id('CommonModule')
            or s.val(m[4]) != s.ZERO or s.val(m[3]) == s.ZERO
            or s.render(m[12]) != '{0}' or s.render(m[13]) != '{0}'
            or s.render(saved[0][12]) != '{0}' or s.render(saved[0][13]) != '{0}'
            or s.metadata_relations(m[14]) != {s.val(m[3]): 1}
            or s.metadata_relations(saved[0][14]) != s.metadata_relations(m[14])):
        raise ValueError('Expected a flat existing CommonModule')
    name = oid + '.0'; refs = m[11]
    if len(refs) != 3 or s.val(refs[0]) != '1' or s.val(refs[1]) != name:
        raise ValueError('Expected the sole module source external stream')
    uuid.UUID(s.val(refs[2]))
    externals = docs[2]
    if (len(externals) != 2 or s.val(externals[0]) != '1' or len(externals[1]) != 3
            or s.val(externals[1][0]) != name or s.val(externals[1][1]) != s.val(refs[2])
            or s.val(externals[1][2]) != '1' or s.render(saved[2]) != '{0}'):
        raise ValueError('Unsupported module external context')
    original = request['original_version'].lower()
    if (not re.fullmatch('[0-9a-f]{40}', original)
            or uuid.UUID(s.val(m[7])).bytes_le.hex() != original[:32]):
        raise ValueError('Source module version mismatch')
    raw = s.inflate(data)
    body = s.Parser(raw.decode('utf-8-sig')).documents()
    if (len(body) != 1 or len(body[0]) != 3 or s.val(body[0][0]) != '1'
            or len(body[0][1]) != 10 or s.val(body[0][1][0]) != '12'):
        raise ValueError('Unsupported module body layout')
    common = body[0][1][1]
    if (len(common) != 9 or s.val(common[0]) != '3' or len(common[1]) != 3
            or s.val(common[1][2]) != oid or s.val(common[2]) != s.val(m[9])):
        raise ValueError('Module body/description mismatch')
    external_data = s.compress(module_container(request['source_text']))
    external_version = uuid.uuid4().bytes_le + bytes(4)
    external64 = base64.b64encode(external_version).decode()
    local = uuid.uuid4().bytes_le + struct.pack('<I', zlib.crc32(raw))
    a = s.atom
    m[0], m[5], m[6] = a(6), a(4294967295), a(0)
    m[7], m[8] = a(base64.b64encode(bytes.fromhex(original)).decode()), a(base64.b64encode(local).decode())
    m[11] = [a(1), a(name, True), a(external64)]
    m[15:17] = copy.deepcopy(saved[0][15:17])
    docs[1] = copy.deepcopy(saved[1])
    docs[2] = [a(1), [a(name, True), a(external64), a(1)]]
    meta = s.text_bytes(docs)
    manifest = s.text_bytes([[a(0), a(1), a(oid), a(hashlib.sha1(meta).hexdigest(), True),
        a(hashlib.sha1(data).hexdigest(), True), a(1), a(name, True), a(hashlib.sha1(external_data).hexdigest(), True)]])
    storage = s.storage([meta, data, external_data], manifest)
    s.validate_storage(storage)
    from constant_serializer import descriptor
    graph = [[a(1), a(oid), descriptor(m)], [a(1), [a(oid), a(0)]],
        [a(1), s.graph_relations(oid, m[14])], [a(1), a(oid), m[3]],
        [a(1), a(oid), a(1)], [a(1), a(oid), [a(0)]], [a(0)],
        [a(1), a(oid), m[11]], [a(1), a(oid), a(1)], [a(1), a(oid), a(1)],
        a(0), [a(0)], a(0), [a(0)], [a(1), [a(0)]]]
    payload = s.SERIALIZER + s.compress(s.record(s.text_bytes([graph])) + bytes(4) + s.record(storage))
    return dict(data=base64.b64encode(payload).decode(), object_id=oid,
        class_id=s.val(m[2]), original=original, local=local.hex(),
        external_name=name, external_version=external_version.hex())


def main():
    from pathlib import Path
    try:
        result = dict(ok=True, **serialize_change(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))))
    except (ValueError, KeyError, IndexError, TypeError, zlib.error) as error:
        result = dict(ok=False, error=str(error))
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__': main()
