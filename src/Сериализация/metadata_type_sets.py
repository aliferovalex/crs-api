"""Verified platform type groups, distinct from repository generated types."""
import json
import re
import uuid
import native_metadata as s
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType


@lru_cache(maxsize=1)
def profile():
    data=json.loads(Path(__file__).with_name('metadata_type_sets_851.json').read_text(encoding='utf-8'))
    if data.get('version')!=1 or not isinstance(data.get('types'),dict):raise ValueError('Invalid platform type-set profile')
    result=dict(data['types'])
    for name,value in result.items():
        if not re.fullmatch(r'cfg:[A-Za-z][A-Za-z0-9]*',name) or not isinstance(value,str) or str(uuid.UUID(value))!=value or uuid.UUID(value).int==0:raise ValueError('Invalid platform type-set identity')
    if len(set(result.values()))!=len(result):raise ValueError('Ambiguous platform type-set UUIDs')
    return MappingProxyType(result)


def is_set(name):
    return name in profile() or name.startswith(('cfg:DefinedType.','cfg:Characteristic.'))


def references(values=None):
    result=dict(profile())
    for name,value in (values or {}).items():
        if name in result and result[name]!=value:raise ValueError('Platform type-set identity cannot be overridden')
        result[name]=value
    return result


@lru_cache(maxsize=1)
def groups():
    data=json.loads(Path(__file__).with_name('metadata_type_sets_851.json').read_text(encoding='utf-8'))
    result=data['groups']
    import metadata_identifiers
    if set(result)!=set(profile()):raise ValueError('Incomplete platform type-set groups')
    for value in result.values():metadata_identifiers.group_id(value)
    return MappingProxyType(dict(result))


def dependencies(names,reader,storage=None):
    labels={groups()[name] for name in names if name in profile()}
    if not labels:return set()
    import metadata_identifiers,configuration_xml
    roots=[row for row in reader.targets.targets if row.class_id==metadata_identifiers.class_id('Configuration')]
    if len(roots)!=1:raise ValueError('Type-set dependencies require one Configuration root')
    root=roots[0];entry=reader.load(root,storage,label='Type-set root')
    actual=configuration_xml.contained_objects(s.Parser(entry.body.decode('utf-8-sig')).documents(),root.object_id,reader.request['platform'])
    values={actual[metadata_identifiers.group_id(label)] for label in labels}
    if not values<=entry.features:raise ValueError('Type-set root feature map differs from native body')
    return values
