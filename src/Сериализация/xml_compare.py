"""Compare complete XML trees and validate metadata names."""
import re
import xml_namespaces

Q = '{' + xml_namespaces.MD + '}'


def canonical(node):
    return [node.tag, dict(node.attrib), (node.text or '') if not len(node) else (node.text or '').strip(),
            [canonical(child) for child in node]]


def name_value(node):
    if node is None or node.attrib or len(node) or not re.fullmatch(r'[^\W\d]\w{0,79}', node.text or '', re.UNICODE):
        raise ValueError('Invalid metadata Name')
    return node.text
