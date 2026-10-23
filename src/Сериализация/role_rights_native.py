"""Native role states and opaque complete restriction matrices.

Extended tables carry a version before the state count and a restriction map
after the states. Restriction contents remain intact; this is not a Rights.xml
compiler and does not infer XML names from their native ordering.
"""
import copy
from dataclasses import dataclass
import uuid
import native_metadata as s


@dataclass(frozen=True)
class Table:
    states: tuple
    restrictions: tuple = ()
    extended: bool = False


def count(node):
    value = s.val(node)
    if not value.isascii() or not value.isdigit() or int(value) > 1000000:
        raise ValueError('Invalid native rights count')
    return int(value)


def guid(node):
    value = s.val(node)
    if str(uuid.UUID(value)) != value:
        raise ValueError('Invalid native right UUID')
    return value


def read(node):
    if not isinstance(node, list) or not node:
        raise ValueError('Invalid native rights table')
    version = count(node[0])
    if version == 0:
        if len(node) % 2 != 1:
            raise ValueError('Invalid native rights pair count')
        start, end, extended = 1, len(node), False
    else:
        if version != 1 or len(node) < 3:
            raise ValueError('Unsupported native rights table version')
        n = count(node[1]); start, end, extended = 2, 2 + n * 2, True
        if end >= len(node):
            raise ValueError('Truncated extended native rights table')
    states = []; seen = set()
    for i in range(start, end, 2):
        oid, value = guid(node[i]), s.val(node[i + 1])
        if oid in seen or value not in ('1', '-1'):
            raise ValueError('Duplicate native right or unsupported state')
        seen.add(oid); states.append((oid, int(value)))
    restrictions = []
    if extended:
        size = count(node[end])
        if len(node) != end + 1 + size:
            raise ValueError('Invalid native restriction map count')
        seen = set()
        for item in node[end + 1:]:
            if not isinstance(item, list) or len(item) != 2:
                raise ValueError('Invalid native restriction entry')
            oid, matrix = guid(item[0]), item[1]
            if oid in seen or not isinstance(matrix, list) or not matrix:
                raise ValueError('Duplicate or invalid native restriction entry')
            if len(matrix) != 1 + count(matrix[0]) or any(not isinstance(row, list) for row in matrix[1:]):
                raise ValueError('Invalid native restriction matrix count')
            seen.add(oid); restrictions.append((oid, copy.deepcopy(matrix)))
    return Table(tuple(states), tuple(restrictions), extended)


def write(table):
    if not isinstance(table, Table) or (table.restrictions and not table.extended):
        raise ValueError('Invalid native rights table value')
    result = [s.atom(len(table.states) if table.extended else 0)]
    for oid, value in table.states:
        result.extend((s.atom(oid), s.atom(value)))
    if table.extended:
        result.insert(0, s.atom(1)); result.append(s.atom(len(table.restrictions)))
        result.extend([s.atom(oid), copy.deepcopy(matrix)] for oid, matrix in table.restrictions)
    read(result)
    return result


def file_references(raw):
    """Actual object and ordinary RLS field UUIDs in a complete role stream.

    Right UUIDs, negative standard codes and standard-attribute class markers
    are not metadata UUID references. Standard fields depend on their owner.
    Unknown field selectors must be mapped before they can participate in a
    destructive dependency check.
    """
    if not isinstance(raw, bytes) or len(raw) > s.MAX_BYTES:
        raise ValueError('Invalid native role file')
    docs = s.Parser(raw.decode('utf-8-sig')).documents()
    if len(docs) != 1 or not isinstance(docs[0], list) or len(docs[0]) != 7 or s.val(docs[0][0]) != '10':
        raise ValueError('Unsupported native role file')
    rows = docs[0][1]
    if not isinstance(rows, list) or not rows or len(rows) != count(rows[0]) + 1:
        raise ValueError('Invalid native role object count')
    result = set()
    for row in rows[1:]:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError('Invalid native role object')
        header = row[0]
        if (not isinstance(header, list) or len(header) not in (4, 5) or s.val(header[0]) != '1'
                or s.val(header[2]) != ('0' if len(header) == 4 else '1')):
            raise ValueError('Unsupported native role reference')
        owner = guid(header[1])
        if owner == s.ZERO:
            raise ValueError('Zero native role reference')
        result.add(owner)
        for _, matrix in read(row[1]).restrictions:
            for condition in matrix[1:]:
                if len(condition) < 3 or len(condition) != 3 + count(condition[2]):
                    raise ValueError('Invalid native restriction fields')
                for path in condition[3:]:
                    if (not isinstance(path, list) or len(path) != 2 or not isinstance(path[0], list)
                            or len(path[0]) not in (1, 2) or s.val(path[0][0]) != '0' or not isinstance(path[1], list)):
                        raise ValueError('Unsupported native role restriction field selector')
                    if len(path[0]) == 2:
                        table_id = guid(path[0][1])
                        if table_id == s.ZERO:
                            raise ValueError('Zero native role table reference')
                        result.add(table_id)
                    if len(path[1]) == 1:
                        if len(path[0]) > 1:
                            raise ValueError('Unsupported native standard tabular restriction field')
                        code = s.val(path[1][0])
                        if len(code) > 11 or not code.startswith('-') or not code[1:].isascii() or not code[1:].isdigit() or not -2147483648 <= int(code) < 0 or str(int(code)) != code:
                            raise ValueError('Invalid native standard restriction field code')
                        # A standard field has no metadata UUID of its own. The
                        # owner is already included by the object header.
                        continue
                    if len(path[1]) != 2 or s.val(path[1][0]) != '0':
                        raise ValueError('Unsupported native role restriction field selector')
                    field = guid(path[1][1])
                    if field == s.ZERO:
                        raise ValueError('Zero native role field reference')
                    result.add(field)
    return frozenset(result)
