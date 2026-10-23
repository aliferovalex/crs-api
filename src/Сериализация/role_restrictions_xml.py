"""Whole role restriction matrices and named templates, independent of right IDs.

Field paths use the caller's metadata context. Native conditions and templates
share the existing XML-to-native text codec; no query text is interpreted.
"""
import copy
from xml.etree import ElementTree as E
import native_metadata as s
import role_rights_native as native
import typed_value_xml

Q = '{http://v8.1c.ru/8.2/roles}'


def container(node):
    if (node.text or '').strip() or any((child.tail or '').strip() for child in node):
        raise ValueError('Unsupported mixed text in role restrictions')


def scalar(node, tag):
    if node.tag != Q + tag or node.attrib or len(node):
        raise ValueError('Unsupported role restriction ' + tag)
    return node.text or ''


def text(value):
    if not isinstance(value, s.Atom) or not value.quoted:
        raise ValueError('Expected quoted native restriction text')
    result = s.val(value).replace('\r\n', '\n')
    if typed_value_xml.native_text(result) != s.val(value):
        raise ValueError('Unsupported native restriction line endings')
    return result


def templates(nodes):
    result = [s.atom(0)]; seen = set()
    for node in nodes:
        container(node)
        if (node.tag != Q + 'restrictionTemplate' or node.attrib
                or [child.tag for child in node] != [Q + 'name', Q + 'condition']):
            raise ValueError('Unsupported role restriction template')
        name = scalar(node[0], 'name'); condition = scalar(node[1], 'condition')
        if not name or name.casefold() in seen:
            raise ValueError('Missing or duplicate role restriction template')
        seen.add(name.casefold())
        result.append([s.atom(name, True), s.atom(typed_value_xml.native_text(condition), True)])
    result[0] = s.atom(len(seen))
    return result


def templates_from_native(values):
    if not isinstance(values, list) or not values or len(values) != 1 + native.count(values[0]):
        raise ValueError('Invalid native restriction template count')
    result = []
    for entry in values[1:]:
        if not isinstance(entry, list) or len(entry) != 2:
            raise ValueError('Invalid native restriction template')
        node = E.Element(Q + 'restrictionTemplate')
        E.SubElement(node, Q + 'name').text = text(entry[0])
        E.SubElement(node, Q + 'condition').text = text(entry[1])
        result.append(node)
    if s.render(templates(result)) != s.render(values):
        raise ValueError('Unrepresentable native restriction templates')
    return result


def matrix(nodes, resolve_field=None):
    rows = []; global_seen = False
    for node in nodes:
        container(node)
        if node.tag != Q + 'restrictionByCondition' or node.attrib or not len(node):
            raise ValueError('Unsupported role restriction condition')
        if node[-1].tag != Q + 'condition' or any(child.tag != Q + 'field' for child in node[:-1]):
            raise ValueError('Expected role restriction fields followed by condition')
        condition = scalar(node[-1], 'condition'); names = [scalar(field, 'field') for field in node[:-1]]
        if not names:
            global_seen = True
        else:
            if resolve_field is None:
                raise ValueError('Role restriction fields require metadata context')
            if any(not name for name in names):
                raise ValueError('Missing role restriction field')
        fields = []
        for name in names:
            path = resolve_field(name)
            if not isinstance(path, list) or not path:
                raise ValueError('Invalid resolved role restriction field')
            fields.append(copy.deepcopy(path))
        rows.append([s.atom(1), s.atom(typed_value_xml.native_text(condition), True), s.atom(len(fields))] + fields)
    # Configurator adds an unrestricted row for all other fields when the XML
    # contains only field-specific conditions.
    if rows and not global_seen:
        rows.insert(0, [s.atom(1), s.atom('', True), s.atom(0)])
    return [s.atom(len(rows))] + rows


def matrix_from_native(values, field_name=None):
    if not isinstance(values, list) or not values or len(values) != 1 + native.count(values[0]):
        raise ValueError('Invalid native restriction matrix count')
    parsed = []
    for row in values[1:]:
        if not isinstance(row, list) or len(row) < 3 or s.val(row[0]) != '1':
            raise ValueError('Unsupported native restriction row version')
        count = native.count(row[2])
        if len(row) != 3 + count:
            raise ValueError('Invalid native restriction field count')
        parsed.append((text(row[1]),count,row[3:]))
    result = []
    for index,(condition,count,fields) in enumerate(parsed):
        # This implicit default is absent from a field-only Rights.xml export.
        if (index == 0 and count == 0 and condition == '' and len(parsed) > 1
                and all(other[1] > 0 for other in parsed[1:])):
            continue
        node = E.Element(Q + 'restrictionByCondition')
        for path in fields:
            if field_name is None:
                raise ValueError('Native restriction fields require metadata context')
            name = field_name(copy.deepcopy(path))
            if not isinstance(name, str) or not name:
                raise ValueError('Invalid native restriction field name')
            E.SubElement(node, Q + 'field').text = name
        E.SubElement(node, Q + 'condition').text = condition
        result.append(node)
    # Verify rows, defaults, field identities and order by compiling the result.
    paths = {}
    for row in values[1:]:
        for path in row[3:]:
            name = field_name(copy.deepcopy(path))
            if name in paths and s.render(paths[name]) != s.render(path):
                raise ValueError('Ambiguous native restriction field name')
            paths[name] = path
    if s.render(matrix(result, paths.__getitem__)) != s.render(values):
        raise ValueError('Unrepresentable native restriction matrix')
    return result
