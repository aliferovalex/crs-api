"""Read the schema-derived metadata map without activating unverified layouts."""
import copy,json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _map():
    return json.loads(Path(__file__).with_name('metadata_structure_221.json').read_text(encoding='utf-8-sig'))


def classes():return copy.deepcopy(_map()['classes'])


def profile(kind):
    matches=[v for v in _map()['classes'].values() if kind in (v['xml_name'],v['runtime_name'])]
    if len(matches)!=1:raise ValueError('Unknown or ambiguous metadata schema class: '+kind)
    return copy.deepcopy(matches[0])


def automatic_owners():
    return frozenset(v['runtime_name'] for v in _map()['classes'].values() if v['automatic_deletion_supported'])


def parents_of(kind):
    return [(v['xml_name'],c['xml_name'],c['storage']) for v in _map()['classes'].values() for c in v['collections']
            if kind in (c['item_type'],c['runtime_item_kind'])]
