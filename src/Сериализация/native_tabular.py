"""Read native tabular sections and their feature UUIDs."""
import json
from functools import lru_cache
from pathlib import Path
import native_metadata as s

Q='{http://v8.1c.ru/8.3/MDClasses}';XR='{http://v8.1c.ru/8.3/xcf/readable}'


@lru_cache(maxsize=1)
def kinds():
    import metadata_structure
    return tuple(sorted({row['runtime_name'] for row in metadata_structure.classes().values()
                         if Path(__file__).with_name(row['runtime_name'].lower()+'_tabular_layout_851.json').is_file()}))


def layout(kind='Catalog'):
    if kind not in kinds():raise ValueError('Unsupported tabular owner kind')
    return json.loads(Path(__file__).with_name(kind.lower()+'_tabular_layout_851.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def attribute_collection_ids():
    return frozenset(layout(kind)['attribute_collection_id'] for kind in kinds())


def collection(source,kind='Catalog'):
    profile=layout(kind);row=source[profile.get('slot',5)]
    if not isinstance(row,list) or len(row)<2 or s.val(row[0])!=profile['collection_id'] or int(s.val(row[1]))!=len(row)-2:raise ValueError('Unsupported tabular section collection')
    return row[2:]


def common(entry):
    try:
        if len(entry)!=3 or (s.val(entry[0][0]),len(entry[0])) not in (('2',3),('2',4),('1',3),('1',4),('0',2)) or len(entry[0][1])!=9 or s.val(entry[0][1][0])!='11' or s.val(entry[1])!='1':raise ValueError('Unsupported TabularSection layout')
        return entry[0][1][5][1]
    except (IndexError,TypeError):raise ValueError('Unsupported TabularSection layout') from None


def attributes(entry):
    common(entry);row=entry[2]
    if not isinstance(row,list) or len(row)<2 or s.val(row[0]) not in attribute_collection_ids() or int(s.val(row[1]))!=len(row)-2:raise ValueError('Unsupported TabularSection Attribute collection')
    return row[2:]


def feature_ids(entry):
    return [s.val(common(entry)[1][2])]+[s.val(a[0][1][1][1][1][2]) for a in attributes(entry)]
