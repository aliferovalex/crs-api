"""Read predefined names/UUIDs from native CF rowsets; never write properties."""
import re
import uuid
import native_metadata as s
import metadata_identifiers as ids

# Native asset routes and rowset families evidenced by ibcmd-rs source_assets.
FAMILIES = {
    'Catalog': ('0', '.1c'),
    'ChartOfCharacteristicTypes': ('1', '.7'),
    'ChartOfAccounts': ('2', '.9'),
    'ChartOfCalculationTypes': ('9', '.2'),
}


def number(node):
    value = s.val(node)
    if not value.isdecimal() or str(int(value)) != value:
        raise ValueError('Invalid predefined rowset count')
    return int(value)


def typed_uuid(node):
    if (not isinstance(node, list) or len(node) != 3 or s.val(node[0]) != '#'
            or s.val(node[1]) != ids.value_type_id('PredefinedIdentity')
            or not isinstance(node[2], list) or len(node[2]) != 2 or s.val(node[2][0]) != '1'):
        raise ValueError('Invalid predefined identity value')
    return str(uuid.UUID(s.val(node[2][1])))


def read(raw, kind):
    try:
        return _read(raw, kind)
    except (IndexError, TypeError, AttributeError, UnicodeError) as error:
        raise ValueError('Invalid native predefined stream: ' + type(error).__name__) from None


def _read(raw, kind):
    if kind not in FAMILIES:raise ValueError('Unsupported predefined owner family: '+str(kind))
    marker, _ = FAMILIES[kind]
    docs = s.Parser(raw.decode('utf-8-sig')).documents()
    if len(docs) != 1 or not isinstance(docs[0], list) or s.val(docs[0][0]) != marker:
        raise ValueError('Predefined stream family differs from its owner')
    root = docs[0]
    if kind == 'ChartOfCalculationTypes':
        if len(root) not in (3, 4) or len(root) == 4 and s.render(root[3]) != '{0,0}':
            raise ValueError('Invalid predefined root rowset')
        schema, rows = root[1:3]
    else:
        if len(root) != 2 or not isinstance(root[1], list) or len(root[1]) not in (3, 5) or s.val(root[1][0]) != '1':
            raise ValueError('Invalid predefined nested rowset')
        schema, rows = root[1][1:3]
    count = number(schema[0])
    if count <= 0 or len(schema) != count + 1:
        raise ValueError('Invalid predefined schema count')
    columns = [number(row[0]) for row in schema[1:]]
    if len(set(columns)) != count or len(rows) not in (3 + 2 * count, 5 + 2 * count) or s.val(rows[0]) != '2' or number(rows[1]) != count:
        raise ValueError('Invalid predefined rowset schema')
    tail = rows[-2:] if len(rows) == 5 + 2 * count else root[1][-2:] if kind != 'ChartOfCalculationTypes' and len(root[1]) == 5 else None
    if tail is not None and (s.val(tail[0]) != '-1' or number(tail[1]) < 0):
        raise ValueError('Invalid predefined rowset tail')
    offsets = {number(rows[pos + 1]): number(rows[pos]) for pos in range(2, 2 + 2 * count, 2)}
    if set(offsets) != set(columns) or set(offsets.values()) != set(range(count)):
        raise ValueError('Invalid predefined column mapping')
    names = {}; identifiers = set(); indexes = set()

    def item_list(node):
        if not isinstance(node, list) or len(node) < 2 or s.val(node[0]) != '1' or number(node[1]) != len(node) - 2:
            raise ValueError('Invalid predefined child count')
        return node[2:]

    def visit(node, synthetic=False):
        if not isinstance(node, list) or len(node) < 4 or s.val(node[0]) != '2':
            raise ValueError('Invalid predefined item row')
        index = number(node[1]); size = number(node[2]); end = 3 + size
        if index in indexes or size > count or len(node) not in (end + 1, end + 2):
            raise ValueError('Invalid predefined row length/index')
        indexes.add(index)
        values = node[3:end]
        id_column = 1 if kind in ('ChartOfCharacteristicTypes', 'ChartOfCalculationTypes') else 0
        if offsets.get(id_column, count) >= size:raise ValueError('Missing predefined identity column')
        identifier = typed_uuid(values[offsets[id_column]])
        if kind == 'ChartOfAccounts':name_offset = offsets.get(1, count)
        elif kind == 'ChartOfCharacteristicTypes':name_offset = offsets.get(3, count)
        elif kind == 'ChartOfCalculationTypes':name_offset = offsets.get(2, count)
        else:
            # Generic/characteristic rows optionally store a reserved parent ref.
            third = values[offsets[2]] if offsets.get(2, count) < size else None
            name_column = 3 if isinstance(third, list) and third and s.val(third[0]) == '#' else 2
            name_offset = offsets.get(name_column, count)
        if name_offset >= size:raise ValueError('Missing predefined name column')
        name = values[name_offset]
        if not isinstance(name, list) or len(name) != 2 or s.val(name[0]) != 'S' or not name[1].quoted:
            raise ValueError('Invalid predefined name value')
        name = s.val(name[1])
        if synthetic:
            if identifier != s.ZERO:raise ValueError('Predefined synthetic root has a nonzero identity')
        else:
            if (identifier == s.ZERO or identifier in identifiers or name.casefold() in names
                    or not re.fullmatch(r'[^\W\d]\w{0,79}', name, re.UNICODE)):
                raise ValueError('Duplicate or invalid predefined item identity/name')
            identifiers.add(identifier);names[name.casefold()] = (name, identifier)
        flag = s.val(node[end])
        if flag == '0' and len(node) == end + 1:return
        if flag != '1' or len(node) != end + 2:raise ValueError('Invalid predefined children flag')
        for child in item_list(node[end + 1]):visit(child)

    roots = item_list(rows[2 + 2 * count])
    if kind == 'ChartOfCalculationTypes':
        for row in roots:visit(row)
    else:
        if len(roots) != 1:raise ValueError('Missing predefined synthetic root')
        visit(roots[0], True)
    return dict(names.values())
