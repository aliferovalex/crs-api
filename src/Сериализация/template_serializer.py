"""Whole XML schema templates and their shared owned-object commit layout."""
import base64
import copy
import re
import uuid
from xml.etree import ElementTree as E
import metadata_serializer as s
import metadata_identifiers as ids
import metadata_localized_xml as localized
import constant_serializer as c
import platform_profiles as platforms
import serialization_context as contexts
import packet_builder as packets
import schema_content
import template_references
import template_content

Q = '{' + c.MD + '}'
OWNERS = {'Catalog', 'Document', 'DataProcessor', 'Report'}


def definition(text, platform):
    if not isinstance(text, str) or len(text.encode('utf-8')) > s.MAX_BYTES or '<!DOCTYPE' in text.upper():
        raise ValueError('Invalid Template XML')
    root = E.fromstring(text)
    if root.tag != Q + 'MetaDataObject' or not platforms.xml_attributes(root.attrib, platform) or \
            len(root) != 1 or root[0].tag not in (Q + 'Template', Q + 'CommonTemplate'):
        raise ValueError('Expected MetaDataObject/Template or CommonTemplate')
    obj = root[0]
    if set(obj.attrib) != {'uuid'} or len(obj) != 1 or obj[0].tag != Q + 'Properties' or obj[0].attrib:
        raise ValueError('Unsupported Template metadata sections')
    fields = {n.tag.removeprefix(Q): n for n in obj[0]}
    if len(fields) != len(obj[0]) or set(fields) != {'Name', 'Synonym', 'Comment', 'TemplateType'} or \
            any(n.tag != Q + key for key, n in fields.items()):
        raise ValueError('Unsupported Template properties')
    for key in ('Name', 'Comment', 'TemplateType'):
        if fields[key].attrib or len(fields[key]):
            raise ValueError('Invalid Template property: ' + key)
    name = fields['Name'].text or ''
    if not re.fullmatch(r'[^\W\d]\w{0,79}', name, re.UNICODE) or fields['TemplateType'].text not in template_content.PROFILES:
        raise ValueError('Expected a named supported template (including DataCompositionSchema)')
    oid = c.guid(obj.get('uuid'));a = s.atom
    common = [a(3), [a(1), a(0), a(oid)], a(name, True), localized.read(fields['Synonym']),
              a(fields['Comment'].text or '', True), a(0), a(0), a(s.ZERO), a(0)]
    return oid, name, common


def native_definition(text, platform):
    oid, name, common = definition(text, platform)
    code=template_content.PROFILES[template_content.kind(text)]['code']
    header = [s.atom(4), common, s.atom(code)] if metadata_kind(text)=='CommonTemplate' else [s.atom(2), s.atom(code), common]
    return oid, name, s.native_body_bytes([[s.atom(1), header, s.atom(0)]])


def metadata_kind(text):
    return E.fromstring(text)[0].tag.removeprefix(Q)


def collection(body, metadata, objects, template_kind='Template'):
    cls = ids.class_id(template_kind);rows = []
    def walk(node):
        if isinstance(node, list):
            if len(node) >= 2 and not isinstance(node[0], list) and s.val(node[0]) == cls:
                rows.append(node)
            for child in node:
                walk(child)
    walk(body)
    pairs = c.children(metadata);expected = {oid for oid, kind in pairs if kind == cls}
    if len(rows) != 1 or int(s.val(rows[0][1])) != len(rows[0])-2 or \
            len(rows[0])-2 != len(expected) or {s.val(v) for v in rows[0][2:]} != expected:
        raise ValueError('Template collection/context mismatch')
    for oid, kind in pairs:
        if oid not in objects or s.val(objects[oid][0][2]) != kind or s.val(objects[oid][0][3]) != s.val(metadata[1]):
            raise ValueError('Invalid owner child context')
    return rows[0], pairs, expected


def create(request):
    oid = c.guid(request['object_id']);fid, name, child_raw = native_definition(request['definition_xml'], request['platform'])
    frame = contexts.read(request, oid);docs, saved, m = frame.docs, frame.saved, frame.metadata
    template_kind=metadata_kind(request['definition_xml'])
    objects = c.context_objects(request['context']);cls = ids.class_id(template_kind)
    kind = ids.class_labels().get(s.val(m[2]))
    allowed={'Configuration'} if template_kind=='CommonTemplate' else OWNERS
    if kind not in allowed or s.val(m[4]) != s.ZERO or fid in objects:
        raise ValueError('Unsupported Template owner or duplicate UUID')
    if (s.render(saved[0][12]) != '{0}' and sorted(c.children(m)) != sorted(c.children(saved[0]))) or \
            s.metadata_relations(m[14]) != s.metadata_relations(saved[0][14]) or s.render(m[13]) != s.render(saved[0][13]):
        raise ValueError('Template owner snapshot/context maps differ')
    original = contexts.original_version(request['original_version'], m)
    raw = s.inflate(frame.data);body = s.Parser(raw.decode('utf-8-sig')).documents()
    if kind=='Configuration':
        common=s.common_properties(body,oid,request['platform'])
        if s.val(m[3])!=s.ZERO:raise ValueError('Expected Configuration root')
    else:common = body[0][1][9][1] if kind in ('Catalog', 'Document') else body[0][1][3][1]
    if kind!='Configuration' and (s.val(common[1][2]) != oid or s.val(common[2]) != s.val(m[9])):
        raise ValueError('Template owner body/metadata identity mismatch')
    row, pairs, expected = collection(body, m, objects,template_kind)
    if any(s.val(objects[key][0][9]).casefold() == name.casefold() for key in expected):
        raise ValueError('Template name already exists')
    position = max((int(s.val(objects[key][0][10])) for key in expected), default=-1)+1
    a = s.atom;changed = [row[0], a(len(row)-1)] + list(row[2:]) + [a(fid)]
    text = raw.decode('utf-8-sig');owner_raw = b'\xef\xbb\xbf'+(text[:row.start]+s.render(changed)+text[row.end:]).encode('utf-8')
    external = template_content.convert(request)
    packets.preserve_external_versions(copy.deepcopy(saved), oid)
    kept = packets.preserve_external_versions(docs, oid)
    versions = {oid: packets.content_version(owner_raw), fid: packets.content_version(child_raw)}
    originals = {oid: bytes.fromhex(original), fid: versions[fid]}
    packets.commit_metadata(m, originals[oid], versions[oid])
    class_row = next((v for v in m[12][1:] if s.val(v[0]) == cls), None)
    if class_row is None:
        m[12][0] = a(len(m[12]));m[12].append([a(cls), a(1), a(fid)])
    else:
        class_row[1] = a(len(class_row)-1);class_row.append(a(fid))
    if kind=='Configuration':
        count=int(s.val(m[14][0]));m[14]=[a(count+1)]+list(m[14][1:1+count])+[a(fid)]+list(m[14][1+count:])+[a(1)]
    m[15:17] = copy.deepcopy(saved[0][15:17]);docs[1] = copy.deepcopy(saved[1])
    stream = fid+'.0';ev = packets.external_version();ev64 = base64.b64encode(ev).decode();local = base64.b64encode(versions[fid]).decode()
    fm = [a(6), a(fid), a(cls), a(oid), a(s.ZERO), a(4294967295), a(0), a(local), a(local), a(name, True), a(position),
          [a(1), a(stream, True), a(ev64)], [a(0)], [a(0)], [a(1), a(oid), a(1)],
          a(('' if kind=='Configuration' else s.val(m[15]))+cls+'.'+name, True), a(0)]
    fd = [fm, copy.deepcopy(saved[1]), [a(1), [a(stream, True), a(ev64), a(0)]]]
    commit = {oid: docs, fid: fd}
    graph = packets.owned_object_creation_graph(commit, oid, fid, pairs+[(fid, cls)])
    payload = packets.assemble(graph, [packets.ObjectRecord(fid, s.text_bytes(fd), s.compress(child_raw), ((stream, s.compress(external)),)),
                                       packets.ObjectRecord(oid, s.text_bytes(docs), s.compress(owner_raw))])
    return dict(object_id=fid, data=base64.b64encode(payload).decode(), version_code='',
                descriptions=[packets.description(commit[key][0], originals[key], versions[key]) for key in (fid, oid)],
                externals=[dict(object_id=fid, name=stream, version=ev.hex(), action=0)]+[dict(object_id=oid, **v) for v in kept])


def change(request):
    import external_data
    oid = c.guid(request['object_id']);frame = contexts.read(request, oid);m = frame.metadata
    template_kind=metadata_kind(request['definition_xml']);common_slot=1 if template_kind=='CommonTemplate' else 2
    fid, name, raw = native_definition(request['definition_xml'], request['platform'])
    if fid != oid or name != s.val(m[9]) or s.val(m[2]) != ids.class_id(template_kind) or s.val(m[4]) != s.ZERO or \
            any(s.render(m[i]) != '{0}' for i in (12, 13)):
        raise ValueError('Template metadata identity or maps mismatch')
    old = s.Parser(s.inflate(frame.data).decode('utf-8-sig')).documents()
    expected = copy.deepcopy(old);expected[0][1][common_slot] = s.Parser(raw.decode('utf-8-sig')).documents()[0][1][common_slot]
    if s.render(expected) != s.render(s.Parser(raw.decode('utf-8-sig')).documents()) or \
            s.val(old[0][1][common_slot][1][2]) != oid or s.val(old[0][1][common_slot][2]) != name:
        raise ValueError('Unsupported source Template definition')
    original = contexts.original_version(request['original_version'], m);stream = oid+'.0'
    if len(m[11]) != 3 or s.val(m[11][0]) != '1' or s.val(m[11][1]) != stream or \
            s.metadata_relations(m[14]) != {s.val(m[3]): 1} or s.metadata_relations(frame.saved[0][14]) != {s.val(m[3]): 1}:
        raise ValueError('Unsupported Template source streams/relations')
    current = external_data.extract(contexts.decode(request['storage'], 'Oversized template storage'), oid)
    if current['class_id'] != s.val(m[2]) or current['parent_id'] != s.val(m[3]) or current['original'] != original[:32] or \
            current['local'] != uuid.UUID(s.val(m[8])).bytes_le.hex() or current['version_number'] != int(s.val(m[5])) or \
            len(current['externals']) != 1 or current['externals'][0]['name'] != stream or \
            current['externals'][0]['version'] != uuid.UUID(s.val(m[11][2])).bytes_le.hex()+'00000000':
        raise ValueError('Template version storage/snapshot mismatch')
    template_content.validate_source(s.inflate(base64.b64decode(current['externals'][0]['data'], validate=True)),request['definition_xml'])
    external = template_content.convert(request)
    return packets.pack_external_change(frame.docs, frame.saved, s.compress(raw), oid, stream, original, raw, s.compress(external))


def serialize(request):
    if not platforms.legacy(request['platform']):
        raise ValueError('Template serialization requires legacy profile')
    operation = request['operation']
    if operation == 'Создание':return create(request)
    if operation == 'Изменение':return change(request)
    raise ValueError('Unsupported Template operation')


if __name__ == '__main__':
    from serializer_cli import run
    run(serialize)
