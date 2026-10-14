"""Full Configurator DataCompositionSchema XML to native schema streams."""
import struct
import uuid
from xml.dom import Node, minidom
from xml.parsers.expat import ExpatError

SCHEMA = 'http://v8.1c.ru/8.1/data-composition-system/schema'
SETTINGS = 'http://v8.1c.ru/8.1/data-composition-system/settings'
AREA = 'http://v8.1c.ru/8.1/data-composition-system/area-template'
XSI = 'http://www.w3.org/2001/XMLSchema-instance'
XMLNS = 'http://www.w3.org/2000/xmlns/'
CORE = 'http://v8.1c.ru/8.1/data/core'
CONFIG = 'http://v8.1c.ru/8.1/data/enterprise/current-config'
MAX_BYTES = 64 * 1024 * 1024


def _parse(raw):
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    if len(raw) > MAX_BYTES:
        raise ValueError('Schema XML exceeds size limit')
    if b'<!DOCTYPE' in raw.upper().replace(b'\x00', b'') or b'<!ENTITY' in raw.upper().replace(b'\x00', b''):
        raise ValueError('Schema XML must not contain a DTD or entities')
    try:
        doc = minidom.parseString(raw)
    except ExpatError as error:
        raise ValueError('Invalid schema XML: ' + str(error)) from None
    if doc.doctype is not None:
        raise ValueError('Schema XML must not contain a DTD')
    return doc


def _elements(node):
    return [child for child in node.childNodes if child.nodeType == Node.ELEMENT_NODE]


def _namespaces(target, source):
    """Keep inherited bindings, including prefixes used only in xsi:type text."""
    ancestors = []
    while source is not None and source.nodeType == Node.ELEMENT_NODE:
        ancestors.append(source)
        source = source.parentNode
    for node in reversed(ancestors):
        for attr in node.attributes.values():
            if attr.namespaceURI == XMLNS:
                target.setAttributeNS(XMLNS, attr.name, attr.value)


def _document(source, uri, name, wrapper=False):
    doc = minidom.Document()
    root = doc.createElementNS(None if wrapper else uri, 'SchemaFile' if wrapper else name)
    doc.appendChild(root)
    _namespaces(root, source)
    root.setAttributeNS(XMLNS, 'xmlns', '' if wrapper else uri)
    if wrapper:
        content = doc.createElementNS(uri, name)
        content.setAttributeNS(XMLNS, 'xmlns', uri)
        root.appendChild(content)
    else:
        content = root
    return doc, content


def _copy(doc, node):
    copied = doc.importNode(node, True)
    if node.nodeType == Node.ELEMENT_NODE:
        _namespaces(copied, node)
    return copied


def _bytes(doc):
    # Formatting is not part of the schema. Keep text nodes (queries, expressions)
    # intact and let the XML parser normalize their logical line breaks.
    return b'\xef\xbb\xbf' + doc.toxml(encoding='UTF-8').replace(b'?>', b'?>\r\n', 1)


def unpack(raw):
    """Validate native framing and return main, variants and layout XML bytes."""
    if len(raw) > MAX_BYTES or len(raw) < 16:
        raise ValueError('Invalid schema stream size')
    reserved, count = struct.unpack_from('<II', raw)
    if reserved != 0 or count > 10000:
        raise ValueError('Invalid schema stream header')
    offset = 8 + 8 * (count + 1)
    if offset > len(raw):
        raise ValueError('Truncated schema stream header')
    lengths = struct.unpack_from('<' + 'Q' * (count + 1), raw, 8)
    parts = []
    for length in lengths:
        if length == 0 or length > len(raw) - offset:
            raise ValueError('Truncated schema XML part')
        parts.append(raw[offset:offset + length])
        offset += length
    if offset == len(raw):
        raise ValueError('Missing schema layout XML')
    parts.append(raw[offset:])
    for part in parts:
        _parse(part)
    return parts


def _qname(node, value):
    prefix, name = value.split(':', 1) if ':' in value else ('', value)
    key = 'xmlns:' + prefix if prefix else 'xmlns'
    parent = node
    while parent is not None and parent.nodeType == Node.ELEMENT_NODE:
        if parent.hasAttribute(key):
            return parent.getAttribute(key), name
        parent = parent.parentNode
    raise ValueError('Unbound schema QName: ' + value)


def _normalize(doc, type_ids, style_ids):
    for node in list(doc.getElementsByTagName('*')):
        if not _elements(node):
            text = ''.join(child.data for child in node.childNodes if child.nodeType == Node.TEXT_NODE)
            if ':' in text and not any(c.isspace() for c in text):
                if node.localName == 'color' or node.getAttributeNS(XSI, 'type') and \
                        _qname(node, node.getAttributeNS(XSI, 'type')) == ('http://v8.1c.ru/8.1/data/ui', 'Color'):
                    uri, name = _qname(node, text)
                    if uri == 'http://v8.1c.ru/8.1/data/ui/style':
                        if name not in style_ids:
                            raise ValueError('Missing schema style UUID: ' + name)
                        for child in list(node.childNodes):
                            node.removeChild(child)
                        node.appendChild(doc.createTextNode('0:' + str(uuid.UUID(style_ids[name]))))
        typed = node.getAttributeNS(XSI, 'type')
        kind = _qname(node, typed) if typed else None
        if node.namespaceURI == SCHEMA and node.localName == 'parameter' and \
                node.parentNode.namespaceURI == SCHEMA and node.parentNode.localName == 'DataCompositionSchema':
            present = {child.localName for child in _elements(node) if child.namespaceURI == SCHEMA}
            for name in ('value', 'useRestriction'):
                if name in present:continue
                child = doc.createElementNS(SCHEMA, node.prefix + ':' + name if node.prefix else name)
                if name == 'value':
                    child.setAttributeNS(XMLNS, 'xmlns:xsi', XSI)
                    child.setAttributeNS(XSI, 'xsi:nil', 'true')
                else:
                    child.appendChild(doc.createTextNode('false'))
                preceding = {'name','title','valueType'} | ({'value'} if name == 'useRestriction' else set())
                following = next((item for item in _elements(node) if item.localName not in preceding), None)
                if following is not None:node.insertBefore(child, following)
                else:node.appendChild(child)
        if kind == ('http://v8.1c.ru/8.3/xcf/readable', 'Picture'):
            import metadata_serializer as s
            import picture_xml
            fields = {item.localName: item for item in _elements(node)}
            if set(fields) != {'Ref', 'LoadTransparent'} or len(_elements(node)) != 2 or any(
                    item.namespaceURI != kind[0] or _elements(item) for item in fields.values()):
                raise ValueError('Unsupported schema Picture XML')
            reference = ''.join(child.data for child in fields['Ref'].childNodes if child.nodeType == Node.TEXT_NODE)
            transparent = ''.join(child.data for child in fields['LoadTransparent'].childNodes if child.nodeType == Node.TEXT_NODE)
            if transparent != 'true' or not reference.startswith('StdPicture.'):
                raise ValueError('Unsupported schema picture reference/transparency')
            native = picture_xml.profile()['references'].get(reference[len('StdPicture.'):])
            if native is None:
                raise ValueError('Unverified schema picture reference: ' + reference)
            values = s.Parser(native).documents()[0]
            if len(values) != 2 or s.val(values[0]) != '0':
                raise ValueError('Unsupported schema picture reference encoding')
            for child in list(node.childNodes):
                node.removeChild(child)
            node.setAttributeNS(XMLNS, 'xmlns:scui', 'http://v8.1c.ru/8.1/data/ui')
            node.setAttributeNS(XSI, 'xsi:type', 'scui:Picture')
            node.setAttribute('ref', '0:' + str(uuid.UUID(s.val(values[1]))))
        defaults = ()
        if node.namespaceURI == SCHEMA and kind == (SCHEMA, 'DataSetFieldField'):
            defaults = ('appearance', 'inputParameters')
        elif node.namespaceURI == AREA and kind == (AREA, 'Field'):
            defaults = ('appearance',)
        elif node.namespaceURI == SETTINGS and (node.localName in ('point', 'series', 'row', 'column') or
                node.localName == 'item' and kind in (
                    (SETTINGS, 'StructureItemGroup'), (SETTINGS, 'StructureItemChart'),
                    (SETTINGS, 'StructureItemTable'))):
            defaults = ('outputParameters',)
        for name in defaults:
            if not any(child.namespaceURI == node.namespaceURI and child.localName == name
                       for child in _elements(node)):
                child = doc.createElementNS(node.namespaceURI, node.prefix + ':' + name if node.prefix else name)
                nested = next((item for item in _elements(node) if item.localName == 'item'), None)
                if name == 'outputParameters' and nested is not None:
                    node.insertBefore(child, nested)
                else:
                    node.appendChild(child)
    for node in list(doc.getElementsByTagNameNS(CORE, 'Type')):
        text = ''.join(child.data for child in node.childNodes if child.nodeType == Node.TEXT_NODE)
        uri, name = _qname(node, text)
        if uri == CONFIG:
            if name not in type_ids:
                raise ValueError('Missing generated schema type UUID: ' + name)
            replacement = doc.createElementNS(CORE, node.prefix + ':TypeId' if node.prefix else 'TypeId')
            _namespaces(replacement, node)
            replacement.appendChild(doc.createTextNode(str(uuid.UUID(type_ids[name]))))
            node.parentNode.replaceChild(replacement, node)
        elif uri == CORE:
            for child in list(node.childNodes):
                node.removeChild(child)
            node.setAttributeNS(XMLNS, 'xmlns', CORE)
            node.appendChild(doc.createTextNode(name))


def convert(raw, type_ids=None, style_ids=None):
    """Convert a complete schema; generated types/styles require current UUID maps.

    The maps use GeneratedType.name/TypeId and StyleItem.Name/uuid from the
    current configuration export. They never use repository or class UUIDs.
    """
    source_doc = _parse(raw)
    source = source_doc.documentElement
    if (source.namespaceURI, source.localName) != (SCHEMA, 'DataCompositionSchema'):
        raise ValueError('Expected Configurator DataCompositionSchema XML')
    _normalize(source_doc, type_ids or {}, style_ids or {})
    main_doc, main = _document(source, SCHEMA, 'dataCompositionSchema', True)
    layout_doc, layout = _document(source, SCHEMA, 'dataCompositionSchema', True)
    settings = []
    for node in _elements(source):
        if node.namespaceURI == SCHEMA and node.localName in ('template', 'fieldTemplate'):
            layout.appendChild(_copy(layout_doc, node))
        else:
            copied = _copy(main_doc, node)
            if node.namespaceURI == SCHEMA and node.localName == 'settingsVariant':
                values = [item for item in _elements(node)
                          if item.namespaceURI == SETTINGS and item.localName == 'settings']
                if len(values) != 1:
                    raise ValueError('Expected one settings element per schema variant')
                setting_doc, setting_root = _document(values[0], SETTINGS, 'Settings')
                for item in values[0].childNodes:
                    setting_root.appendChild(_copy(setting_doc, item))
                settings.append(_bytes(setting_doc))
                for item in list(_elements(copied)):
                    if item.namespaceURI == SETTINGS and item.localName == 'settings':
                        copied.removeChild(item)
            main.appendChild(copied)
    # Native area templates share table-cell formatting via an indexed pool.
    cells = list(layout.getElementsByTagNameNS(AREA, 'tableCell'))
    for cell in cells:
        appearances = [item for item in _elements(cell)
                       if item.namespaceURI == AREA and item.localName == 'appearance']
        if len(appearances) > 1 or any(item.namespaceURI == AREA and item.localName == 'appIndex'
                                      for item in _elements(cell)):
            raise ValueError('Invalid Configurator table-cell appearance')
        if appearances:
            appearance = appearances[0]
            pooled = layout_doc.createElementNS(AREA, 'appearance')
            _namespaces(pooled, appearance)
            pooled.setAttributeNS(XMLNS, 'xmlns', AREA)
            pooled.setAttributeNS(XMLNS, 'xmlns:xsi', XSI)
            pooled.setAttributeNS(XSI, 'xsi:type', 'TableCellAppearance')
            for item in appearance.childNodes:
                pooled.appendChild(_copy(layout_doc, item))
            index = layout_doc.createElementNS(AREA, cell.prefix + ':appIndex' if cell.prefix else 'appIndex')
            index.appendChild(layout_doc.createTextNode(str(len(_elements(layout_doc.documentElement)) - 1)))
            cell.replaceChild(index, appearance)
            layout_doc.documentElement.appendChild(pooled)
    parts = [_bytes(main_doc)] + settings
    result = struct.pack('<II', 0, len(settings))
    result += struct.pack('<' + 'Q' * len(parts), *(len(part) for part in parts))
    result += b''.join(parts) + _bytes(layout_doc)
    if len(result) > MAX_BYTES:
        raise ValueError('Native schema exceeds size limit')
    return result
