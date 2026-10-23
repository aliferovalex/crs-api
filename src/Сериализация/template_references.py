"""Resolve schema type/style names from the validated current repository version."""
import json
import uuid
from pathlib import Path
import schema_content as xml
import native_metadata as s
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
    import native_references
    source=native_references.catalog(request)
    storage=contexts.decode(request['storage'],'Schema references require current version storage') if 'storage' in request else None
    def current(kind, name):
        identity=source.select(kind,name,label='Schema reference')
        return source.load(identity,storage,label='Schema reference')
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
        kind, position, layout, categories = selected[0];entry=current(kind,name);identity=entry.identity
        body=s.Parser(entry.body.decode('utf-8-sig')).documents()[0]
        common = body
        from metadata_object_xml import common_path
        for slot in common_path(layout):common = common[slot]
        if s.val(common[1][2]) != identity.object_id or s.val(common[2]) != name or len(layout['generated_slots']) != len(categories)*2:
            raise ValueError('Schema reference native identity/layout mismatch')
        types[reference] = str(uuid.UUID(s.val(body[1][layout['generated_slots'][position*2]])))
    for name in wanted_styles:
        entry=current('StyleItem', name);styles[name] = entry.identity.object_id
    if 'type_ids' in request and request['type_ids'] != types or 'style_ids' in request and request['style_ids'] != styles:
        raise ValueError('Explicit schema UUID map differs from current repository')
    return types, styles
