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
from pathlib import Path
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


def xml_property_patches(before_text, after_text, object_id, common, documents, platform='8.5.4.1878', allowed=None,allow_unchanged=False):
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
    for key in allowed if allowed is not None else ('Comment', 'Synonym', *PROPERTY_SLOTS):
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
    if not patches and not allow_unchanged:
        raise ValueError('Supported XML properties have not changed')
    return patches


def configuration_xml_values(after_text, object_id, common, documents, platform, allowed=None):
    """Read every supported target property, including unchanged values.

    XML validation protects unsupported sections separately. All provided target
    values are serialized, including unchanged values.
    """
    root = ET.fromstring(after_text)
    config = next(e for e in root.iter() if e.tag.rsplit('}',1)[-1]=='Configuration')
    properties = next(e for e in config if e.tag.rsplit('}',1)[-1]=='Properties')
    values = {e.tag.rsplit('}',1)[-1]:e for e in properties}
    result=[]
    for key in allowed if allowed is not None else ('Comment','Synonym',*PROPERTY_SLOTS):
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


def configuration_baseline_from_snapshot(after_text, object_id, common, documents, platform, context):
    """Validate a target XML against the native snapshot, without a prior dump.

    Unmapped properties are accepted only for the verified default native profile.
    Omitted properties remain intact; children and internal IDs cannot be edited.
    """
    if '<!DOCTYPE' in after_text.upper():
        raise ValueError('DOCTYPE is unsupported')
    root = ET.fromstring(after_text)
    local = lambda e: e.tag.rsplit('}', 1)[-1]
    if local(root) != 'MetaDataObject' or len(root) != 1 or local(root[0]) != 'Configuration':
        raise ValueError('Expected one Configuration XML object')
    if any(key != 'version' for key in root.attrib) or root.get('version', '2.21') != '2.21':
        raise ValueError('Unsupported Configuration XML version or attributes')
    config = root[0]
    if config.attrib != {'uuid': object_id}:
        raise ValueError('XML must contain the requested Configuration UUID')
    sections = {}
    for node in config:
        key = local(node)
        if key not in ('Properties', 'InternalInfo', 'ChildObjects') or key in sections or node.attrib:
            raise ValueError('Unsupported or duplicate Configuration section: ' + key)
        sections[key] = node
    if 'Properties' not in sections:
        raise ValueError('Missing Configuration.Properties')
    props = sections['Properties']; names = [local(n) for n in props]
    if len(set(names)) != len(names):
        raise ValueError('Duplicate XML property')
    supported = {'Name', 'Comment', 'Synonym', *PROPERTY_SLOTS}
    for node in props:
        if local(node) in supported and (node.attrib or (local(node) != 'Synonym' and len(node))):
            raise ValueError('Unsupported XML property attributes or children')
    unmapped = [n for n in props if local(n) not in supported]
    def canonical(e):
        return [e.tag, [list(pair) for pair in sorted(e.attrib.items())],
                (e.text or '') if not len(e) else (e.text or '').strip(), [canonical(c) for c in e]]
    if unmapped:
        if not platforms.legacy(platform):
            raise ValueError('Unmapped Configuration properties require the verified legacy profile')
        profile = json.loads(Path(__file__).with_name('configuration_profile_851.json').read_text(encoding='utf-8'))
        native = configuration_properties(documents, platform)
        if render(common[5:]) != profile['common_tail'] or any(render(native[int(i)]) != value for i, value in profile['native_slots'].items()):
            raise ValueError('Source Configuration properties are outside the verified native profile')
        # The default language is a reference, so resolve its actual name from context.
        import constant_serializer as c
        objects = c.context_objects(context)
        for node in unmapped:
            key = local(node)
            if key == 'DefaultLanguage':
                lang = val(native[10])
                expected = '' if lang == ZERO else 'Language.' + val(objects[lang][0][9])
                if node.attrib or len(node) or (node.text or '') != expected:
                    raise ValueError('Unsupported Configuration.DefaultLanguage change')
            elif key not in profile['xml_properties'] or canonical(node) != profile['xml_properties'][key]:
                raise ValueError('Unsupported Configuration property: ' + key)
    if 'InternalInfo' in sections:
        actual = {ROOT_FEATURE_CLASS: val(common[1][2]).lower()}
        def ids(node):
            result = []
            if isinstance(node, list):
                if len(node) == 3 and all(isinstance(x, Atom) for x in node) and [val(x) for x in node[:2]] == ['1','0']:
                    result.append(val(node[2]).lower())
                for child in node: result.extend(ids(child))
            return result
        for group in documents[0][3:]:
            if isinstance(group, list) and len(group) == 2 and isinstance(group[0], Atom):
                if val(group[0]) == ROOT_FEATURE_CLASS: continue
                found = ids(group[1])
                if len(found) == 1: actual[val(group[0])] = found[0]
        expected = {}
        for node in sections['InternalInfo']:
            if local(node) != 'ContainedObject' or node.attrib or len(node) != 2 or [local(n) for n in node] != ['ClassId','ObjectId'] or any(n.attrib or len(n) for n in node):
                raise ValueError('Unsupported Configuration.InternalInfo')
            cls, oid = [(n.text or '').lower() for n in node]
            if cls in expected: raise ValueError('Duplicate internal class')
            expected[cls] = oid
        if expected != actual:
            raise ValueError('XML internal UUIDs do not match native body')
    if 'ChildObjects' in sections:
        import constant_serializer as c
        objects = c.context_objects(context)
        expected = []
        for oid, cls in c.children(context_metadata(base64.b64decode(context), object_id)[0]):
            name = identifiers.class_labels().get(cls)
            if name is None: raise ValueError('Unknown Configuration child class')
            expected.append((name, val(objects[oid][0][9])))
        target = sections['ChildObjects']
        if any(n.attrib or len(n) for n in target) or sorted((local(n), n.text or '') for n in target) != sorted(expected):
            raise ValueError('Configuration child changes are unsupported')
    # Existing validation checks scalar/synonym shape and protects all XML attributes.
    for node in props:
        key = local(node)
        if key == 'Comment': node.text = val(common[4])
        elif key in PROPERTY_SLOTS: node.text = val(configuration_properties(documents, platform)[PROPERTY_SLOTS[key]])
        elif key == 'Synonym':
            node[:] = []
            for lang, content in synonym_value(common[3]):
                item = ET.SubElement(node, '{http://v8.1c.ru/8.1/data/core}item')
                ET.SubElement(item, '{http://v8.1c.ru/8.1/data/core}lang').text = lang
                ET.SubElement(item, '{http://v8.1c.ru/8.1/data/core}content').text = content
    return ET.tostring(root, encoding='unicode')


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
    import packet_builder as packets
    platforms.profile(request['platform'])
    mode = request.get('mode', 'comment')
    if mode not in ('comment', 'properties'):
        raise ValueError('Unsupported serialization mode')
    allowed = ('Comment',) if mode == 'comment' else None
    for key in ('snapshot', 'context', 'after_xml'):
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
    before_xml = request.get('before_xml')
    if before_xml is None:
        before_xml = configuration_baseline_from_snapshot(request['after_xml'], object_id, common, documents, request['platform'], request['context'])
    if not isinstance(before_xml, str) or len(before_xml) > MAX_BYTES * 2:
        raise ValueError('Oversized or invalid baseline XML')
    if platforms.legacy(request['platform']) and request.get('before_xml') is not None:
        if '<!DOCTYPE' in before_xml.upper():
            raise ValueError('DOCTYPE is unsupported')
        before_root = ET.fromstring(before_xml)
        refs = []
        for contained in before_root.iter():
            if contained.tag.rsplit('}', 1)[-1] == 'ContainedObject':
                fields = {e.tag.rsplit('}', 1)[-1]: e.text for e in contained}
                if fields.get('ClassId', '').lower() == ROOT_FEATURE_CLASS:
                    refs.append(fields.get('ObjectId', '').lower())
        if refs != [val(common[1][2]).lower()]:
            raise ValueError('XML common properties UUID does not match native body')
    xml_property_patches(before_xml, request['after_xml'], object_id, common, documents, request['platform'], allowed)
    patches = configuration_xml_values(request['after_xml'], object_id, common, documents, request['platform'], allowed)
    new_text = text
    for start, end, replacement in sorted(patches, reverse=True):
        new_text = new_text[:start] + replacement + new_text[end:]
    new_raw = b"\xef\xbb\xbf" + new_text.encode("utf-8")
    new_data = compress(new_raw)
    # Experimental client version; this does not reproduce the native hash algorithm.
    version_bytes = packets.content_version(new_raw)
    packets.commit_metadata(m, bytes.fromhex(original), version_bytes)
    m[15:17] = copy.deepcopy(saved[15:17])
    new_meta = text_bytes(meta)
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
    graph = packets.change_graph(m, child_types, features)
    payload = packets.assemble(graph, [packets.ObjectRecord(object_id, new_meta, new_data)])
    xml = packets.request_xml(request, payload, {object_id: meta}, {object_id: bytes.fromhex(original)}, {object_id: version_bytes})
    return xml, new_raw


def main():
    # All paths and object data arrive through JSON, never shell interpolation.
    from serializer_cli import run
    run(lambda request: {"request_xml": serialize(request)[0]})


if __name__ == "__main__":
    # Helpers import this module too; retain one AST class identity in CLI mode.
    sys.modules['metadata_serializer'] = sys.modules[__name__]
    main()
