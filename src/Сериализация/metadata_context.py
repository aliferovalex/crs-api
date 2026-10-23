"""Repository updateInfo readers, UUID validation and stored child maps."""
import base64
import uuid
import native_metadata as s
from native_metadata import HEADER, MAX_BYTES, Parser, read_record, val


def guid(value):
    result = str(uuid.UUID(value))
    if result == s.ZERO:
        raise ValueError('Zero UUID is forbidden')
    return result


def context_objects(encoded):
    if not isinstance(encoded,str) or len(encoded)>s.MAX_BYTES*2:
        raise ValueError('Oversized or invalid context')
    data = base64.b64decode(encoded, validate=True)
    s.validate_storage(data)
    pos, objects = 12, {}
    while pos < len(data):
        raw, pos = s.read_record(data, pos)
        if not raw.startswith(b'\xef\xbb\xbf{5,'):
            break
        docs = s.Parser(raw.decode('utf-8-sig')).documents()
        m = docs[0]
        if len(docs) != 3 or len(m) != 17 or s.val(m[0]) != '5':
            raise ValueError('Unsupported context metadata')
        oid = guid(s.val(m[1]))
        if oid in objects:
            raise ValueError('Duplicate context UUID')
        objects[oid] = docs
    return objects


def children(metadata):
    result = []
    group = metadata[12]
    if int(s.val(group[0])) != len(group)-1:
        raise ValueError('Invalid child class map')
    for row in group[1:]:
        if int(s.val(row[1])) != len(row)-2:
            raise ValueError('Invalid child class count')
        result.extend((guid(s.val(oid)), s.val(row[0])) for oid in row[2:])
    if len({oid for oid, _ in result}) != len(result):
        raise ValueError('Duplicate child UUID')
    return result


def context_metadata(data, object_id):
    if data[:8] != HEADER[:8] or len(data) > MAX_BYTES:
        raise ValueError("Unsupported updateInfo context")
    pos, found = 12, []
    while pos < len(data):
        raw, pos = read_record(data, pos)
        if not raw.startswith(b"\xef\xbb\xbf{5,"):
            break
        docs = Parser(raw.decode("utf-8-sig")).documents()
        if val(docs[0][1]).lower() == object_id.lower():
            found.append(docs)
    if len(found) != 1:
        raise ValueError("Object missing or duplicated in updateInfo context")
    return found[0]
