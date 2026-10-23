"""Role references use actual stored/inline UUIDs from the final XML definitions.

Ordinary and standard-attribute headers and RLS paths share real owner IDs.
Only verified standard fields are enabled; nested selectors remain explicit errors.
"""
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import metadata_definitions
import native_metadata as s


@lru_cache(maxsize=1)
def profile():
    result = json.loads(Path(__file__).with_name('role_reference_kinds.json').read_text(encoding='utf-8'))
    if (type(result.get('header_version')) is not int or result['header_version'] != 1
            or type(result.get('ordinary_selector')) is not int or result['ordinary_selector'] != 0
            or not isinstance(result.get('kinds'), dict)
            or any(type(flag) is not int or flag not in (0, 1) for flag in result['kinds'].values())):
        raise ValueError('Invalid role reference profile')
    return result


@lru_cache(maxsize=1)
def standard_profile():
    result = json.loads(Path(__file__).with_name('role_standard_attributes_851.json').read_text(encoding='utf-8'))
    if (type(result.get('version')) is not int or result['version'] != 1
            or any(type(result.get(key)) is not int or result[key] != 1 for key in ('header_version', 'selector', 'attribute_flag'))
            or not isinstance(result.get('kinds'), dict) or not result['kinds']
            or metadata_definitions.guid(result.get('class_id')) != result['class_id']):
        raise ValueError('Invalid standard role selector profile')
    for kind, fields in result['kinds'].items():
        if (not isinstance(kind, str) or not kind or not isinstance(fields, dict) or not fields
                or any(not isinstance(name, str) or not name or type(code) is not int or not -2147483648 <= code < 0 for name, code in fields.items())
                or len(set(fields.values())) != len(fields)):
            raise ValueError('Invalid standard attribute code map')
    fields = result.get('rls_fields')
    if (not isinstance(fields, dict) or set(fields) - set(result['kinds'])
            or any(not isinstance(names, list) or len(names) != len(set(names))
                   or set(names) - set(result['kinds'][kind]) for kind, names in fields.items())):
        raise ValueError('Invalid standard RLS field profile')
    return result


@dataclass(frozen=True)
class Field:
    name: str
    definition: metadata_definitions.Definition
    standard_code: int = None
    ancestors: tuple = ()


class Context:
    def __init__(self, definitions):
        if not isinstance(definitions, metadata_definitions.Index):
            raise ValueError('Role references require a metadata definition index')
        self.definitions = definitions

    def flag(self, entry):
        try:
            return profile()['kinds'][entry.kind]
        except KeyError:
            raise ValueError('Unmapped metadata kind for role reference: ' + entry.kind) from None

    def standard(self, name):
        parts = name.split('.') if isinstance(name, str) else []
        if len(parts) < 4 or len(parts) % 2 or parts[-2] != 'StandardAttribute':
            return None
        owner = self.definitions.resolve('.'.join(parts[:-2]))
        try:
            code = standard_profile()['kinds'][owner.kind][parts[-1]]
        except KeyError:
            raise ValueError('Unmapped standard role attribute: ' + name) from None
        return owner, parts[-1], code

    def definition(self, name):
        """Standard selectors depend on the real owner, without a fake UUID."""
        standard = self.standard(name)
        return standard[0] if standard is not None else self.definitions.resolve(name)

    def reference(self, name):
        standard = self.standard(name)
        if standard is not None:
            owner, _, code = standard; rule = standard_profile()
            return [s.atom(rule['header_version']), s.atom(owner.object_id), s.atom(rule['selector']),
                    [s.atom(code), s.atom(rule['class_id'])], s.atom(rule['attribute_flag'])]
        entry = self.definition(name)
        return [s.atom(profile()['header_version']), s.atom(entry.object_id),
                s.atom(profile()['ordinary_selector']), s.atom(self.flag(entry))]

    def reference_name(self, value):
        if not isinstance(value, list) or len(value) not in (4, 5):
            raise ValueError('Unsupported standard or nested role metadata selector')
        entry = self.definitions.by_id(s.val(value[1]))
        name = entry.qualified_name
        if len(value) == 5:
            selector = value[3]
            if (not isinstance(selector, list) or len(selector) != 2
                    or s.val(selector[1]) != standard_profile()['class_id']):
                raise ValueError('Unsupported standard or nested role metadata selector')
            matches = [field for field, code in standard_profile()['kinds'].get(entry.kind, {}).items() if str(code) == s.val(selector[0])]
            if len(matches) != 1:
                raise ValueError('Unmapped native standard role attribute')
            name += '.StandardAttribute.' + matches[0]
        if s.render(value) != s.render(self.reference(name)):
            raise ValueError('Role metadata header differs from definition')
        return name

    def field(self, owner, name):
        parent = self.definitions.resolve(owner)
        if not isinstance(name, str) or not name:
            raise ValueError('Missing role restriction field name')
        parts = name.split('.')
        if len(parts) > 1:
            if len(parts) != 2 or any(not part for part in parts):
                raise ValueError('Deeper role restriction fields require additional selector rules')
            tables = [entry for entry in self.definitions.children(parent.object_id)
                      if entry.kind == 'TabularSection' and not entry.stored and entry.name == parts[0]]
            if len(tables) != 1:
                raise ValueError('Missing or ambiguous role restriction tabular section: ' + parts[0])
            table = tables[0]
            fields = [entry for entry in self.definitions.children(table.object_id)
                      if entry.kind == 'Attribute' and not entry.stored and entry.name == parts[1]]
            if len(fields) != 1:
                raise ValueError('Missing or unsupported nested role restriction field: ' + name)
            return Field(name, fields[0], ancestors=(table,))
        candidates = []
        for entry in self.definitions.children(parent.object_id):
            if entry.name == name and not entry.stored and self.flag(entry) == 1:
                candidates.append(entry)
        if len(candidates) > 1:
            raise ValueError('Ambiguous ordinary role restriction field: ' + name)
        code = standard_profile()['kinds'].get(parent.kind, {}).get(name)
        if candidates and code is not None:
            raise ValueError('Ambiguous ordinary and standard role restriction field: ' + name)
        if candidates:
            return Field(name, candidates[0])
        if code is not None:
            if name not in standard_profile()['rls_fields'].get(parent.kind, ()):
                raise ValueError('Unsupported standard role restriction field: ' + parent.kind + '.' + name)
            return Field(name, parent, code)
        raise ValueError('Missing ordinary or standard role restriction field: ' + name)

    def field_path(self, owner, name):
        field = self.field(owner, name)
        selector = [s.atom(field.standard_code)] if field.standard_code is not None else [s.atom(0), s.atom(field.definition.object_id)]
        return [[s.atom(0)] + [s.atom(entry.object_id) for entry in field.ancestors], selector]

    def field_name(self, owner, path):
        if (not isinstance(path, list) or len(path) != 2 or not isinstance(path[0], list)
                or len(path[0]) not in (1, 2) or s.val(path[0][0]) != '0' or not isinstance(path[1], list)):
            raise ValueError('Unsupported standard or nested role field path')
        owner_entry = self.definitions.resolve(owner)
        parent = owner_entry
        prefix = ''
        if len(path[0]) == 2:
            table = self.definitions.by_id(s.val(path[0][1]))
            if table.kind != 'TabularSection' or table.stored or table.parent_id != parent.object_id:
                raise ValueError('Role restriction table belongs to another metadata owner')
            parent = table; prefix = table.name + '.'
        if len(path[1]) == 1:
            if prefix:
                raise ValueError('Unsupported standard tabular role restriction field')
            parent = self.definitions.resolve(owner)
            matches = [field for field in standard_profile()['rls_fields'].get(parent.kind, ())
                       if str(standard_profile()['kinds'][parent.kind][field]) == s.val(path[1][0])]
            if len(matches) != 1:
                raise ValueError('Unmapped native standard role restriction field')
            name = matches[0]
            if s.render(path) != s.render(self.field_path(owner, name)):
                raise ValueError('Standard role field path differs from definition')
            return name
        if len(path[1]) != 2 or s.val(path[1][0]) != '0':
            raise ValueError('Unsupported standard or nested role field path')
        entry = self.definitions.by_id(s.val(path[1][1]))
        if entry.stored or parent.object_id != entry.parent_id or self.flag(entry) != 1:
            raise ValueError('Role restriction field belongs to another metadata owner')
        name = prefix + entry.name
        if s.render(path) != s.render(self.field_path(owner, name)):
            raise ValueError('Role field path differs from definition')
        return name
