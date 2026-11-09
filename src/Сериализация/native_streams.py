"""Classify owned CF streams; this module never converts their contents."""
import json
from pathlib import Path
import metadata_structure
import native_metadata as s
import uuid

_ROUTES = json.loads(Path(__file__).with_name('native_asset_routes.json').read_text(encoding='utf-8'))['routes']


def routes(kind):
    """Export paths share the same format facts as dependency classification."""
    kind=family(kind)
    return {row['suffix']:row for row in _ROUTES if row['family']==kind}


def identities(metadata):
    """A stream can belong to the object or a declared embedded feature."""
    group=metadata[13]
    if not isinstance(group,list) or not group or s.val(group[0])!=str(len(group)-1):
        raise ValueError('Invalid native stream feature map')
    values=[str(uuid.UUID(s.val(value))) for value in [metadata[1],*group[1:]]]
    if len(set(values))!=len(values):raise ValueError('Duplicate native stream owner identity')
    return set(values)


def select(metadata,names):
    owned=identities(metadata)
    return {name for name in names if '.' in name and name.partition('.')[0] in owned and name.partition('.')[2]}


def family(kind):
    if kind=='CommonForm':return kind
    if kind.endswith('Form'):return 'Form'
    return metadata_structure.profile(kind)['xml_name']


def roles(kind, object_id, names):
    """Unknown owned companions are opaque, not inferred from their bytes."""
    codecs={'Module':'module','Help':'help','Predefined':'predefined',
            'ManagedForm':'managed-form','Rights':'rights','Template':'template-content'}
    known={suffix:codecs.get(row['codec'],'opaque') for suffix,row in routes(kind).items()}
    result={}
    for name in sorted(names):
        if not name.startswith(object_id+'.') or name==object_id+'.':
            raise ValueError('External stream belongs to another object: '+name)
        result[name]=known.get(name[len(object_id):],'opaque')
    return result
