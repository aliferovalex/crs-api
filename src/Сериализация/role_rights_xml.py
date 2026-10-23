"""Compile the complete Rights.xml file with final metadata identities.

The input is the exported role file, including all conditions and templates.
Object/header and field identities come from the common role metadata context.
"""
from xml.etree import ElementTree as E
from dataclasses import asdict
import native_metadata as s
import role_metadata_context
import role_restrictions_xml as restrictions
import role_right_identifiers as identifiers
import role_rights_native as native
import xml_namespaces

Q = restrictions.Q
XSI = '{http://www.w3.org/2001/XMLSchema-instance}'
FLAGS = ('setForNewObjects', 'setForAttributesByDefault', 'independentRightsOfChildObjects')
# Configurator 8.5.1 emits explicit denials for these compatibility rights when
# a Configuration row exists, even when absent from its exported XML row.
ROOT_DEFAULT_DENIALS = ('MainWindowModeNormal', 'MainWindowModeWorkplace',
                      'MainWindowModeEmbeddedWorkplace', 'MainWindowModeFullscreenWorkplace',
                      'MainWindowModeKiosk', 'AnalyticsSystemClient')


def boolean(node, tag):
    text = restrictions.scalar(node, tag)
    if text not in ('true', 'false', '1', '0'):
        raise ValueError('Invalid role Boolean: ' + tag)
    return text in ('true', '1')


def parse(raw):
    """Validate the whole XML before requiring metadata or emitting streams."""
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    if not isinstance(raw, bytes) or len(raw) > s.MAX_BYTES or b'<!DOCTYPE' in raw.upper():
        raise ValueError('Invalid or oversized Rights.xml')
    try:
        top, scopes = xml_namespaces.parse(raw.decode('utf-8-sig'))
    except (UnicodeError, E.ParseError):
        raise ValueError('Invalid Rights.xml') from None
    if (top.tag != Q + 'Rights' or set(top.attrib) - {'version', XSI + 'type'}
            or top.get('version') not in ('2.20', '2.21')):
        raise ValueError('Unsupported Rights.xml root or version')
    declared_type = top.get(XSI + 'type')
    if declared_type is not None:
        parts = declared_type.split(':')
        if (parts[-1] != 'Rights' or len(parts) > 2
                or scopes[top].get(parts[0] if len(parts) == 2 else '', '') != Q[1:-1]):
            raise ValueError('Unsupported Rights.xml type')
    restrictions.container(top)
    if [node.tag for node in top[:3]] != [Q + flag for flag in FLAGS]:
        raise ValueError('Missing or reordered role flags')
    for node, flag in zip(top[:3], FLAGS):
        boolean(node, flag)
    owners = set(); templates = []; templates_started = False
    for obj in top[3:]:
        if obj.tag == Q + 'restrictionTemplate':
            templates_started = True
            templates.append(obj)
            continue
        if obj.tag != Q + 'object' or obj.attrib or templates_started or not len(obj):
            raise ValueError('Unsupported role object or XML section')
        restrictions.container(obj)
        name = restrictions.scalar(obj[0], 'name')
        if not name or name.casefold() in owners:
            raise ValueError('Missing or duplicate role object')
        owners.add(name.casefold()); seen = set()
        for right in obj[1:]:
            restrictions.container(right)
            if right.tag != Q + 'right' or right.attrib or len(right) < 2:
                raise ValueError('Unsupported role right')
            right_name = restrictions.scalar(right[0], 'name')
            identifiers.right_id(right_name)
            if right_name in seen:
                raise ValueError('Duplicate role right: ' + right_name)
            seen.add(right_name); boolean(right[1], 'value')
            # Validate complete condition grammar now; field identities are
            # checked against final definitions during compilation.
            restrictions.matrix(right[2:], lambda field: [s.atom(field, True)])
    restrictions.templates(templates)
    return top


def compile(raw, context=None):
    top = parse(raw)
    objects = top.findall(Q + 'object')
    if objects and not isinstance(context, role_metadata_context.Context):
        raise ValueError('Role rights require final XML metadata definitions')
    rows = []
    for obj in objects:
        name = restrictions.scalar(obj[0], 'name')
        header = context.reference(name)
        states = []; matrices = []; seen = set()
        for right in obj[1:]:
            identifier = identifiers.right_id(restrictions.scalar(right[0], 'name'))
            seen.add(identifier)
            states.append((identifier, 1 if boolean(right[1], 'value') else -1))
            if len(right) > 2:
                matrices.append((identifier, restrictions.matrix(right[2:], lambda field: context.field_path(name, field))))
        if context.definition(name).kind == 'Configuration':
            for right_name in ROOT_DEFAULT_DENIALS:
                identifier = identifiers.right_id(right_name)
                if identifier not in seen:
                    states.append((identifier, -1))
        table = native.Table(tuple(states), tuple(matrices), bool(matrices))
        rows.append([header, native.write(table)])
    flags = [boolean(node, flag) for node, flag in zip(top[:3], FLAGS)]
    body = [s.atom(10), [s.atom(len(rows))] + rows,
            restrictions.templates(top.findall(Q + 'restrictionTemplate')),
            s.atom(1 if flags[0] else 4294967295),
            s.atom(1 if flags[1] else 4294967295), s.atom(int(flags[2])), s.atom(4294967295)]
    return s.native_body_bytes([body])


def required_definitions(raw, definitions):
    """Only identities used by this role, its RLS fields and their ancestors."""
    context = role_metadata_context.Context(definitions)
    needed = set()
    def add(entry):
        if entry.object_id in needed:
            return
        needed.add(entry.object_id)
        if entry.parent_id != s.ZERO:
            add(definitions.by_id(entry.parent_id))
    for obj in parse(raw).findall(Q + 'object'):
        name = restrictions.scalar(obj[0], 'name')
        context.reference(name)
        add(context.definition(name))
        for right in obj[1:]:
            for condition in right[2:]:
                for field in condition[:-1]:
                    add(context.field(name, restrictions.scalar(field, 'field')).definition)
    return [asdict(definitions.by_id(key)) for key in sorted(needed)]
