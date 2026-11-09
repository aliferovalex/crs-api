"""Read native schema containers for dependency validation."""
import struct
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
