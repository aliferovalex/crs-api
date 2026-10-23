"""Native token trees, binary records, compression and repository storage framing."""
import hashlib
import re
import struct
import uuid
import zlib
from dataclasses import dataclass


NS = "http://v8.1c.ru/8.2/crs"


ZERO = "00000000-0000-0000-0000-000000000000"


SERIALIZER = bytes.fromhex("0201534b6ff4888dc14ea0d5ebb6bda0a70d")


EOF_MARKER = bytes.fromhex("eee6eb24e5811f44ab292f34ce20ab33")


HEADER = struct.pack("<III", 0x11223344, 2, 3)


MAX_BYTES = 16 * 1024 * 1024

_QUOTED = re.compile(r'"[^"]*(?:""[^"]*)*"(?!")')
_TOKEN = re.compile(r'[^,}]*')


class Group(list):
    def __init__(self, items, start, end):
        super().__init__(items)
        self.start, self.end = start, end


@dataclass
class Atom:
    value: str
    quoted: bool = False
    start: int = -1
    end: int = -1


class Parser:
    def __init__(self, text):
        self.text, self.pos = text, 0

    def whitespace(self):
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def value(self, depth=0):
        if depth > 128:
            raise ValueError("Serialization nesting limit exceeded")
        self.whitespace()
        start = self.pos
        if self.pos >= len(self.text):
            raise ValueError("Truncated serialization")
        if self.text[self.pos] == "{":
            self.pos += 1
            items = []
            while True:
                self.whitespace()
                if self.pos >= len(self.text):
                    raise ValueError("Unclosed serialization group")
                if self.text[self.pos] == "}":
                    self.pos += 1
                    return Group(items, start, self.pos)
                items.append(self.value(depth + 1))
                self.whitespace()
                if self.pos < len(self.text) and self.text[self.pos] == ",":
                    self.pos += 1
                elif self.pos >= len(self.text) or self.text[self.pos] != "}":
                    raise ValueError("Expected serialization separator")
        if self.text[self.pos] == '"':
            match = _QUOTED.match(self.text, start)
            if match is None:
                self.pos = len(self.text)
                raise ValueError("Unclosed quoted string")
            self.pos = match.end()
            return Atom(self.text[start + 1:self.pos - 1].replace('""', '"'), True, start, self.pos)
        self.pos = _TOKEN.match(self.text, start).end()
        token = self.text[start:self.pos].strip()
        if not token or "{" in token or '"' in token:
            raise ValueError("Invalid serialization token")
        return Atom(token, False, start, self.pos)

    def documents(self):
        result = []
        while True:
            self.whitespace()
            if self.pos == len(self.text):
                return result
            result.append(self.value())
            self.whitespace()
            if self.pos < len(self.text):
                if self.text[self.pos] != ",":
                    raise ValueError("Trailing serialization data")
                self.pos += 1


def atom(value, quoted=False):
    return Atom(str(value), quoted)


def val(node):
    if not isinstance(node, Atom):
        raise ValueError("Expected scalar serialization value")
    return node.value


def render(node):
    if isinstance(node, list):
        return "{" + ",".join(render(x) for x in node) + "}"
    return '"' + node.value.replace('"', '""') + '"' if node.quoted else node.value


def text_bytes(documents):
    return b"\xef\xbb\xbf" + ",".join(render(x) for x in documents).encode("utf-8")


def render_native_text(node):
    """Verified 8.5.1/8.5.4 object text: CRLF before groups and after final groups."""
    if not isinstance(node, list):
        return render(node)
    items = [("\r\n" if isinstance(child, list) else "") + render_native_text(child)
             for child in node]
    closing = "\r\n" if node and isinstance(node[-1], list) else ""
    return "{" + ",".join(items) + closing + "}"


def native_body_bytes(documents):
    from v8unpack_backend import assemble,to_model
    return assemble(to_model(documents))


def record(data):
    return struct.pack("<Q", len(data)) + data


def read_record(data, pos):
    if pos + 8 > len(data):
        raise ValueError("Truncated storage record")
    size = struct.unpack_from("<Q", data, pos)[0]
    if size > MAX_BYTES or pos + 8 + size > len(data):
        raise ValueError("Invalid storage record size")
    return data[pos + 8:pos + 8 + size], pos + 8 + size


def storage(records, manifest):
    """SHA1-indexed native storage, with index and whole-stream checksums."""
    count = len({hashlib.sha1(p).digest() for p in records + [manifest]})
    data = bytearray(struct.pack('<III', 0x11223344, 2, count))
    offsets = {}
    for payload in records + [manifest]:
        digest = hashlib.sha1(payload).digest()
        if digest not in offsets:
            offsets[digest] = len(data)
            data += record(payload)
    index = bytes.fromhex('11223344') + struct.pack('<II', 2, count)
    for digest, offset in sorted(offsets.items()):
        index += digest + struct.pack("<Q", offset)
    index += bytes(20)
    index += hashlib.sha1(index).digest()
    data += record(index)
    data += struct.pack("<Q", len(index) + 8 + 64)
    data += hashlib.sha1(manifest).digest() + EOF_MARKER
    data += hashlib.sha1(data).digest()
    return bytes(data)


def inflate(data):
    decoder = zlib.decompressobj(-15)
    raw = decoder.decompress(data, MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or not decoder.eof or decoder.unused_data:
        raise ValueError("Invalid or oversized raw DEFLATE")
    return raw


def validate_storage(data):
    """Validate the index, all indexed records and both SHA1 checksums."""
    if len(data) < 128 or len(data) > MAX_BYTES or data[:8] != HEADER[:8]:
        raise ValueError("Unsupported or oversized native storage")
    count = struct.unpack_from('<I', data, 8)[0]
    if data[-36:-20] != EOF_MARKER or hashlib.sha1(data[:-20]).digest() != data[-20:]:
        raise ValueError("Native storage checksum mismatch")
    index_pos = len(data) - struct.unpack_from("<Q", data, len(data) - 64)[0]
    if index_pos < 12 or index_pos >= len(data) - 64:
        raise ValueError("Invalid native index offset")
    index, end = read_record(data, index_pos)
    index_header = bytes.fromhex('11223344') + struct.pack('<II', 2, count)
    if end != len(data) - 64 or index[:12] != index_header or len(index) < 52:
        raise ValueError("Invalid native index")
    if index[-40:-20] != bytes(20) or hashlib.sha1(index[:-20]).digest() != index[-20:]:
        raise ValueError("Native index checksum mismatch")
    if (len(index) - 52) % 28:
        raise ValueError("Invalid native index entries")
    records, pos = {}, 12
    while pos < index_pos:
        offset = pos
        payload, pos = read_record(data, pos)
        digest = hashlib.sha1(payload).digest()
        if pos > index_pos or digest in records:
            raise ValueError("Invalid or duplicate native record")
        records[digest] = offset
    entries = {}
    previous = None
    for p in range(12, len(index) - 40, 28):
        digest = index[p:p + 20]
        if previous is not None and digest <= previous:
            raise ValueError("Unsorted or duplicate native index")
        entries[digest] = struct.unpack_from("<Q", index, p + 20)[0]
        previous = digest
    if pos != index_pos or entries != records or len(records) != count or data[-56:-36] not in records:
        raise ValueError("Native index does not match storage records")


def compress(data):
    encoder = zlib.compressobj(wbits=-15)
    return encoder.compress(data) + encoder.flush()


def graph_relations(object_id, relation):
    """Metadata stores UUID and flag columns; graph stores interleaved pairs."""
    pairs = metadata_relations(relation)
    row = [atom(object_id), atom(len(pairs))]
    for target, flag in pairs.items():
        row.extend([atom(target), atom(flag)])
    return row


def metadata_relations(relation):
    count = int(val(relation[0]))
    if len(relation) != 1 + count * 2:
        raise ValueError('Invalid metadata relation count')
    pairs = {}
    for target, flag in zip(relation[1:1 + count], relation[1 + count:]):
        key = str(uuid.UUID(val(target)))
        if key in pairs or val(flag) not in ('0', '1'):
            raise ValueError('Invalid or duplicate metadata relation')
        pairs[key] = int(val(flag))
    return pairs
