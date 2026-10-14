"""Resolve schema type/style names from the validated current repository version."""
import base64
import json
import uuid
from pathlib import Path
import schema_content as xml
import metadata_serializer as s
import metadata_identifiers as ids
import constant_serializer as c
import external_data
import serialization_context as contexts


def required(raw):
    doc = xml._parse(raw);types = set();styles = set()
    for node in doc.getElementsByTagName('*'):
        text = ''.join(child.data for child in node.childNodes if child.nodeType == child.TEXT_NODE)
        if node.namespaceURI == xml.CORE and node.localName == 'Type':
            uri, name = xml._qname(node, text)
            if uri == xml.CONFIG:types.add(name)
        typed = node.getAttributeNS(xml.XSI, 'type')
        if not xml._elements(node) and ':' in text and not any(ch.isspace() for ch in text) and (
                node.localName == 'color' or typed and xml._qname(node, typed) == ('http://v8.1c.ru/8.1/data/ui', 'Color')):
            uri, name = xml._qname(node, text)
            if uri == 'http://v8.1c.ru/8.1/data/ui/style':styles.add(name)
    return types, styles


def resolve(request):
    wanted_types, wanted_styles = required(request['template_xml'])
    if not wanted_types and not wanted_styles:return {}, {}
    objects = c.context_objects(request['context']);storage = contexts.decode(request['storage'], 'Schema references require current version storage')
    index = {};labels = ids.class_labels()
    for oid, docs in objects.items():
        m = docs[0];key = (labels.get(s.val(m[2])), s.val(m[9]))
        index.setdefault(key, []).append((oid, m))
    def current(kind, name):
        if (kind, name) not in index:raise ValueError('Schema reference is missing: '+kind+'.'+name)
        if len(index[(kind, name)]) != 1:raise ValueError('Ambiguous schema reference metadata')
        oid, m = index[(kind, name)][0];record = external_data.extract(storage, oid)
        if record['class_id'] != s.val(m[2]) or record['parent_id'] != s.val(m[3]) or record['version_number'] != int(s.val(m[5])) or \
                record['original'] != uuid.UUID(s.val(m[7])).bytes_le.hex() or record['local'] != uuid.UUID(s.val(m[8])).bytes_le.hex():
            raise ValueError('Schema reference version/context mismatch')
        return oid, m, record
    types = {};styles = {}
    from object_xml_profiles import profiles
    for reference in wanted_types:
        prefix, separator, name = reference.partition('.')
        if not separator:raise ValueError('Invalid generated schema type: '+reference)
        selected = []
        for kind in profiles():
            layout = json.loads(Path(__file__).with_name(kind.lower()+'_layout_851.json').read_text(encoding='utf-8'))
            categories = layout.get('generated_categories', ('Object','Ref','Selection','List','Manager'))
            if prefix in [kind+category for category in categories] and layout.get('generated_slots'):
                selected.append((kind, categories.index(prefix[len(kind):]), layout, categories))
        if len(selected) != 1:raise ValueError('Unverified generated schema type: '+reference)
        kind, position, layout, categories = selected[0];oid, m, record = current(kind, name)
        body = s.Parser(s.inflate(base64.b64decode(record['data'], validate=True)).decode('utf-8-sig')).documents()[0]
        common = body
        for slot in layout.get('common_path', [1,9,1]):common = common[slot]
        if s.val(common[1][2]) != oid or s.val(common[2]) != name or len(layout['generated_slots']) != len(categories)*2:
            raise ValueError('Schema reference native identity/layout mismatch')
        types[reference] = str(uuid.UUID(s.val(body[1][layout['generated_slots'][position*2]])))
    for name in wanted_styles:
        oid, _, _ = current('StyleItem', name);styles[name] = oid
    if 'type_ids' in request and request['type_ids'] != types or 'style_ids' in request and request['style_ids'] != styles:
        raise ValueError('Explicit schema UUID map differs from current repository')
    return types, styles
