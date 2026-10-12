"""Native metadata storage primitives and Configuration property serialization.

Uses a current server snapshot and updateInfo context, never a captured commit.
Python 3.9+, standard library only. No network or repository mutations.
"""
import base64
import copy
import hashlib
import json
import re
import struct
import sys
import uuid
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
import metadata_identifiers as identifiers
import platform_profiles as platforms

NS = "http://v8.1c.ru/8.2/crs"
ROOT_CLASS = identifiers.class_id('Configuration')
BASIC_FEATURE = "b3b0b503-7bab-411e-bf30-7a7c0925a441"
ZERO = "00000000-0000-0000-0000-000000000000"
SERIALIZER = bytes.fromhex("0201534b6ff4888dc14ea0d5ebb6bda0a70d")
EOF_MARKER = bytes.fromhex("eee6eb24e5811f44ab292f34ce20ab33")
HEADER = struct.pack("<III", 0x11223344, 2, 3)
INDEX_HEADER = bytes.fromhex("11223344") + struct.pack("<II", 2, 3)
MAX_BYTES = 16 * 1024 * 1024
PROPERTY_SLOTS = {'NamePrefix': 42, 'Vendor': 14, 'Version': 15, 'UpdateCatalogAddress': 16}
ROOT_FEATURE_CLASS = identifiers.group_id('General')


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
            self.pos += 1
            chars = []
            while self.pos < len(self.text):
                c = self.text[self.pos]
                self.pos += 1
                if c == '"':
                    if self.pos < len(self.text) and self.text[self.pos] == '"':
                        self.pos += 1
                        chars.append('"')
                    else:
                        return Atom("".join(chars), True, start, self.pos)
                else:
                    chars.append(c)
            raise ValueError("Unclosed quoted string")
        while self.pos < len(self.text) and self.text[self.pos] not in ",}":
            self.pos += 1
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
    return b"\xef\xbb\xbf" + ",".join(render_native_text(x) for x in documents).encode("utf-8")


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


def xml_comment(before_text, after_text, object_id, name, current_comment):
    if "<!DOCTYPE" in before_text.upper() or "<!DOCTYPE" in after_text.upper():
        raise ValueError("DOCTYPE is unsupported")
    before, after = ET.fromstring(before_text), ET.fromstring(after_text)
    def target(root):
        configs = [e for e in root.iter() if e.tag.rsplit("}", 1)[-1] == "Configuration"]
        if len(configs) != 1 or configs[0].get("uuid", "").lower() != object_id.lower():
            raise ValueError("XML must contain the requested Configuration UUID")
        props = [e for e in configs[0] if e.tag.rsplit("}", 1)[-1] == "Properties"]
        if len(props) != 1:
            raise ValueError("Missing or duplicate Configuration.Properties")
        comments = [e for e in props[0] if e.tag.rsplit("}", 1)[-1] == "Comment"]
        names = [e for e in props[0] if e.tag.rsplit("}", 1)[-1] == "Name"]
        if len(comments) != 1 or len(names) != 1 or (names[0].text or "") != name or len(comments[0]):
            raise ValueError("Invalid Name or Comment in XML")
        return comments[0]
    source, changed = target(before), target(after)
    if (source.text or "") != current_comment:
        raise ValueError("Baseline XML Comment does not match the server snapshot")
    new_comment = changed.text or ""
    if new_comment == current_comment:
        raise ValueError("XML Comment has not changed")
    source.text = changed.text
    def canonical(e):
        # Ignore indentation between elements, preserve all leaf property text.
        return (e.tag, sorted(e.attrib.items()), (e.text or "") if not len(e) else (e.text or "").strip(),
                (e.tail or "").strip(), tuple(canonical(c) for c in e))
    if canonical(before) != canonical(after):
        raise ValueError("Only Configuration.Comment may change; other XML changes are unsupported")
    return new_comment


def common_properties(node, object_id, platform='8.5.4.1878'):
    # Configuration stores common properties under its feature ID, not root UUID.
    if (len(node) != 1 or not isinstance(node[0], list) or len(node[0]) < 2
            or val(node[0][0]) != "2" or not isinstance(node[0][1], list)
            or len(node[0][1]) != 1 or val(node[0][1][0]).lower() != object_id.lower()):
        raise ValueError("Object content UUID does not match the Configuration root")
    if platforms.legacy(platform):
        props = configuration_properties(node, platform)
        wrapper = props[1]
        if not isinstance(wrapper, list) or len(wrapper) != 2 or val(wrapper[0]) != '0':
            raise ValueError('Unsupported 8.5.1 common properties wrapper')
        common = wrapper[1]
        if (not isinstance(common, list) or len(common) != 9 or val(common[0]) != '3'
                or not isinstance(common[1], list) or len(common[1]) != 3
                or [val(v) for v in common[1][:2]] != ['1', '0']
                or not isinstance(common[4], Atom) or not common[4].quoted):
            raise ValueError('Unsupported 8.5.1 common properties layout')
        if str(uuid.UUID(val(common[1][2]))) == ZERO:
            raise ValueError('Zero common properties UUID')
        return common
    found = []
    def walk(n):
        if not isinstance(n, list):
            return
        if (len(n) >= 5 and isinstance(n[0], Atom) and val(n[0]) == "4"
                and isinstance(n[1], list) and len(n[1]) == 3
                and all(isinstance(x, Atom) for x in n[1])
                and [val(x) for x in n[1]][:2] == ["1", "0"]
                and val(n[1][2]).lower() == BASIC_FEATURE):
            found.append(n)
        for child in n:
            walk(child)
    walk(node)
    if len(found) != 1 or not isinstance(found[0][4], Atom) or not found[0][4].quoted:
        raise ValueError("Unsupported common properties layout")
    return found[0]


def configuration_properties(documents, platform='8.5.4.1878'):
    groups = [g for g in documents[0][3:] if isinstance(g, list) and len(g) == 2
              and isinstance(g[0], Atom) and val(g[0]) == ROOT_FEATURE_CLASS]
    if len(groups) != 1:
        raise ValueError('Unsupported Configuration feature layout')
    outer = groups[0][1]
    if len(outer) < 2 or val(outer[0]) != '1' or not isinstance(outer[1], list):
        raise ValueError('Unsupported Configuration feature version')
    props = outer[1]
    count, length = platforms.configuration_layout(platform)
    if len(props) != length or val(props[0]) != str(count):
        raise ValueError('Unsupported Configuration property layout for ' + platform)
    for index in PROPERTY_SLOTS.values():
        if not isinstance(props[index], Atom) or not props[index].quoted:
            raise ValueError('Unsupported string property layout')
    return props


def synonym_value(node):
    if not isinstance(node, list) or not node or int(val(node[0])) * 2 != len(node) - 1:
        raise ValueError('Invalid native Synonym count')
    pairs = []
    for i in range(1, len(node), 2):
        if not all(isinstance(n, Atom) and n.quoted for n in node[i:i + 2]):
            raise ValueError('Unsupported native Synonym layout')
        pairs.append((val(node[i]), val(node[i + 1])))
    if len({p[0] for p in pairs}) != len(pairs):
        raise ValueError('Duplicate native Synonym language')
    return pairs


def xml_property_patches(before_text, after_text, object_id, common, documents, platform='8.5.4.1878'):
    if '<!DOCTYPE' in before_text.upper() or '<!DOCTYPE' in after_text.upper():
        raise ValueError('DOCTYPE is unsupported')
    before, after = ET.fromstring(before_text), ET.fromstring(after_text)
    def properties(root):
        configs = [e for e in root.iter() if e.tag.rsplit('}', 1)[-1] == 'Configuration']
        if len(configs) != 1 or configs[0].get('uuid', '').lower() != object_id:
            raise ValueError('XML must contain the requested Configuration UUID')
        nodes = [e for e in configs[0] if e.tag.rsplit('}', 1)[-1] == 'Properties']
        if len(nodes) != 1:
            raise ValueError('Missing or duplicate Configuration.Properties')
        return nodes[0]
    source, changed = properties(before), properties(after)
    def canonical(e):
        return (e.tag, sorted(e.attrib.items()), (e.text or '') if not len(e) else (e.text or '').strip(),
                (e.tail or '').strip(), tuple(canonical(c) for c in e))
    def unique(parent, name, required=True):
        nodes = [e for e in parent if e.tag.rsplit('}', 1)[-1] == name]
        if len(nodes) > 1 or (required and not nodes):
            raise ValueError('Missing or duplicate XML property: ' + name)
        return nodes[0] if nodes else None
    for props in (source, changed):
        name = unique(props, 'Name')
        if len(name) or (name.text or '') != val(common[2]):
            raise ValueError('Configuration.Name changes are unsupported')
    def xml_synonym(node):
        pairs = []
        for item in node:
            if item.tag != '{http://v8.1c.ru/8.1/data/core}item' or len(item) != 2 or item.attrib:
                raise ValueError('Unsupported XML Synonym item')
            lang, content = unique(item, 'lang'), unique(item, 'content')
            if (lang.tag != '{http://v8.1c.ru/8.1/data/core}lang'
                    or content.tag != '{http://v8.1c.ru/8.1/data/core}content'
                    or len(lang) or len(content) or lang.attrib or content.attrib or not (lang.text or '')):
                raise ValueError('Invalid XML Synonym language or content')
            pairs.append((lang.text, content.text or ''))
        if len({p[0] for p in pairs}) != len(pairs):
            raise ValueError('Duplicate XML Synonym language')
        return pairs
    patches = []
    props = None
    for key in ('Comment', 'Synonym', *PROPERTY_SLOTS):
        old, new = unique(source, key, False), unique(changed, key, False)
        if old is None and new is None:
            continue
        if old is None or new is None:
            raise ValueError('Both XML documents must contain property: ' + key)
        if key == 'Synonym':
            token = common[3]
            baseline, value = xml_synonym(old), xml_synonym(new)
            current = synonym_value(token)
            native = [atom(len(value))]
            for lang, content in value:
                native.extend([atom(lang, True), atom(content, True)])
        else:
            if len(old) or len(new):
                raise ValueError('Expected scalar XML property: ' + key)
            if key == 'Comment':
                token = common[4]
            else:
                if props is None:
                    props = configuration_properties(documents, platform)
                token = props[PROPERTY_SLOTS[key]]
            baseline, value, current = old.text or '', new.text or '', val(token)
            native = atom(value, True)
        if baseline != current:
            raise ValueError('Baseline XML ' + key + ' does not match the server snapshot')
        if baseline != value:
            patches.append((token.start, token.end, render(native)))
        # Only value changes are allowed; attributes and unrelated XML remain checked.
        old.text = new.text
        old[:] = copy.deepcopy(list(new))
    if canonical(before) != canonical(after):
        raise ValueError('Unsupported XML changes outside supported Configuration properties')
    if not patches:
        raise ValueError('Supported XML properties have not changed')
    return patches


def configuration_xml_values(after_text, object_id, common, documents, platform):
    """Read every supported target property, including unchanged values.

    The baseline validator still protects unsupported XML sections. It is not
    used as a list of changes to apply.
    """
    root = ET.fromstring(after_text)
    config = next(e for e in root.iter() if e.tag.rsplit('}',1)[-1]=='Configuration')
    properties = next(e for e in config if e.tag.rsplit('}',1)[-1]=='Properties')
    values = {e.tag.rsplit('}',1)[-1]:e for e in properties}
    result=[]
    for key in ('Comment','Synonym',*PROPERTY_SLOTS):
        if key not in values:
            continue
        node=values[key]
        if key=='Synonym':
            token=common[3]; native=[atom(len(node))]
            for item in node:
                native.extend([atom(item[0].text or '',True),atom(item[1].text or '',True)])
        else:
            token=common[4] if key=='Comment' else configuration_properties(documents,platform)[PROPERTY_SLOTS[key]]
            native=atom(node.text or '',True)
        result.append((token.start,token.end,render(native)))
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


def serialize(request):
    platforms.profile(request['platform'])
    for key in ('snapshot', 'context', 'before_xml', 'after_xml'):
        if not isinstance(request[key], str) or len(request[key]) > MAX_BYTES * 2:
            raise ValueError("Oversized or invalid serializer input")
    snapshot = base64.b64decode(request["snapshot"], validate=True)
    context = base64.b64decode(request["context"], validate=True)
    validate_storage(snapshot)
    validate_storage(context)
    object_id = str(uuid.UUID(request["object_id"]))
    if snapshot[:12] != HEADER or len(snapshot) > MAX_BYTES:
        raise ValueError("Unsupported snapshot")
    old_meta_bytes, pos = read_record(snapshot, 12)
    old_data, pos = read_record(snapshot, pos)
    old_meta = Parser(old_meta_bytes.decode("utf-8-sig")).documents()
    meta = context_metadata(context, object_id)
    m, saved = meta[0], old_meta[0]
    if len(meta) != 3 or len(old_meta) != 3 or val(m[0]) != "5" or val(saved[0]) != "5":
        raise ValueError("Unsupported metadata format")
    if len(m) != 17 or len(saved) != 17 or val(m[1]).lower() != object_id or val(saved[1]).lower() != object_id:
        raise ValueError("Unsupported object metadata")
    if val(m[2]) != ROOT_CLASS or val(m[3]) != ZERO or val(m[4]) != ZERO:
        raise ValueError("Only an existing Configuration root is supported")
    if [val(m[i]) for i in (2, 5, 6, 7, 8)] != [val(saved[i]) for i in (2, 5, 6, 7, 8)]:
        raise ValueError("Snapshot and updateInfo context versions differ")
    if render(m[11]) != "{0}" or render(meta[2]) != "{0}":
        raise ValueError("External object changes are unsupported")
    original = request["original_version"].lower()
    if not re.fullmatch("[0-9a-f]{40}", original) or uuid.UUID(val(m[7])).bytes_le.hex() != original[:32]:
        raise ValueError("Source version mismatch")
    original_raw = inflate(old_data)
    if not original_raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Unsupported object text encoding")
    text = original_raw.decode("utf-8-sig")
    documents = Parser(text).documents()
    common = common_properties(documents, object_id, request['platform'])
    if platforms.legacy(request['platform']):
        if '<!DOCTYPE' in request['before_xml'].upper():
            raise ValueError('DOCTYPE is unsupported')
        before_root = ET.fromstring(request['before_xml'])
        refs = []
        for contained in before_root.iter():
            if contained.tag.rsplit('}', 1)[-1] == 'ContainedObject':
                fields = {e.tag.rsplit('}', 1)[-1]: e.text for e in contained}
                if fields.get('ClassId', '').lower() == ROOT_FEATURE_CLASS:
                    refs.append(fields.get('ObjectId', '').lower())
        if refs != [val(common[1][2]).lower()]:
            raise ValueError('XML common properties UUID does not match native body')
    mode = request.get('mode', 'comment')
    if mode == 'comment':
        new_comment = xml_comment(request["before_xml"], request["after_xml"], object_id, val(common[2]), val(common[4]))
        patches = [(common[4].start, common[4].end, render(atom(new_comment, True)))]
    elif mode == 'properties':
        xml_property_patches(request['before_xml'], request['after_xml'], object_id, common, documents, request['platform'])
        patches = configuration_xml_values(request['after_xml'], object_id, common, documents, request['platform'])
    else:
        raise ValueError('Unsupported serialization mode')
    new_text = text
    for start, end, replacement in sorted(patches, reverse=True):
        new_text = new_text[:start] + replacement + new_text[end:]
    new_raw = b"\xef\xbb\xbf" + new_text.encode("utf-8")
    new_data = compress(new_raw)
    # Experimental client version; this does not reproduce the native hash algorithm.
    version_bytes = uuid.uuid4().bytes_le + struct.pack("<I", zlib.crc32(new_raw))
    local = version_bytes.hex()
    original64 = base64.b64encode(bytes.fromhex(original)).decode()
    local64 = base64.b64encode(version_bytes).decode()
    m[0], m[5], m[6], m[7], m[8] = atom(6), atom(4294967295), atom(0), atom(original64), atom(local64)
    m[15:17] = copy.deepcopy(saved[15:17])
    new_meta = text_bytes(meta)
    manifest = text_bytes([[atom(0), atom(1), atom(object_id),
                            atom(hashlib.sha1(new_meta).hexdigest(), True),
                            atom(hashlib.sha1(new_data).hexdigest(), True), atom(0)]])
    snapshot_out = storage([new_meta, new_data], manifest)
    features = copy.deepcopy(m[13])
    children = []
    for group in (m[12], m[13]):
        if not isinstance(group, list) or not group or int(val(group[0])) != len(group) - 1:
            raise ValueError("Invalid metadata group count")
    if not isinstance(m[14], list) or not m[14] or int(val(m[14][0])) * 2 != len(m[14]) - 1:
        raise ValueError("Invalid metadata relation count")
    for group in m[12][1:]:
        if len(group) < 2 or int(val(group[1])) != len(group) - 2:
            raise ValueError("Invalid child class map")
        children.extend([[copy.deepcopy(child), copy.deepcopy(group[0])] for child in group[2:]])
    child_types = [atom(len(children))]
    for pair in children:
        child_types.extend(pair)
    descriptor = [atom(object_id), copy.deepcopy(m[2]), atom(ZERO), copy.deepcopy(m[9]), copy.deepcopy(m[10]),
                  atom(4294967295), atom(0), copy.deepcopy(m[3]), copy.deepcopy(m[4]), atom(original64), atom(local64), atom(0)]
    graph = [[atom(1), atom(object_id), descriptor], [atom(1), [atom(object_id)] + features],
             [atom(1), graph_relations(object_id, m[14])], [atom(1), atom(object_id), copy.deepcopy(m[3])],
             [atom(1), atom(object_id), atom(1)], [atom(1), atom(object_id), child_types], [atom(0)],
             [atom(1), atom(object_id), [atom(0)]], [atom(1), atom(object_id), atom(1)],
             [atom(1), atom(object_id), atom(1)], atom(0), [atom(0)], atom(0), [atom(0)], [atom(1), [atom(0)]]]
    raw = record(text_bytes([graph])) + struct.pack("<I", 0) + record(snapshot_out)
    payload = SERIALIZER + compress(raw)
    ET.register_namespace("crs", NS)
    root = ET.Element("{%s}call" % NS, alias=request["repository"], name="DevDepot_commitObjects", version=request["platform"])
    def element(parent, tag, value=None, text=None):
        e = ET.SubElement(parent, "{%s}%s" % (NS, tag))
        if value is not None:
            e.set("value", str(value))
        e.text = text
        return e
    params = element(root, "params")
    element(params, "clientVerID", str(uuid.UUID(request["repository_version"])))
    element(params, "data", text=base64.b64encode(payload).decode())
    for section in ("requested", "changes"):
        entry = element(element(params, section), "value")
        element(entry, "first", object_id)
        second = element(entry, "second")
        detail = element(second, "_super") if section == "changes" else second
        supernode = element(detail, "_super")
        element(supernode, "id", object_id)
        element(supernode, "classID", ROOT_CLASS)
        for key, value in (("name", val(m[9])), ("pos", val(m[10])), ("verNum", -1), ("selfVerNum", 0),
                           ("parentID", val(m[3])), ("ownerID", val(m[4]))):
            element(detail, key, value)
        v = element(detail, "version")
        element(v, "original", original)
        element(v, "local", local)
        element(detail, "removed", "false")
        if section == "changes":
            element(second, "externals")
    element(params, "objectsToRemove")
    element(params, "code", "")
    element(params, "comment", text="")
    element(params, "features")
    return ET.tostring(root, encoding="unicode"), new_raw


def main():
    # All paths and object data arrive through JSON, never shell interpolation.
    from pathlib import Path
    try:
        request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
        xml, _ = serialize(request)
        result = {"ok": True, "request_xml": xml}
    except (ValueError, KeyError, IndexError, TypeError, zlib.error, ET.ParseError) as error:
        result = {"ok": False, "error": str(error)}
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
