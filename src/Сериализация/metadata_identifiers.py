"""Named access to the shared metadata UUID dictionary (no network)."""
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def _dictionary():
    return json.loads(Path(__file__).with_name('metadata_class_names.json').read_text(encoding='utf-8-sig'))


def class_id(name):
    for identifier, label in _dictionary()['names'].items():
        if label == name:
            return identifier
    # XML names and repository labels differ for some classes (e.g. Types/Type).
    import metadata_structure
    try:
        runtime = metadata_structure.profile(name)['runtime_name']
    except ValueError:
        runtime = None
    for identifier, label in _dictionary()['names'].items():
        if label == runtime:
            return identifier
    raise ValueError('Unknown metadata class: ' + str(name))


def group_id(name):
    return _identifier('groups', name)


def feature_id(name):
    return _identifier('features', name)


def value_type_id(name):
    return _identifier('value_types', name)


def _identifier(section, name):
    try:
        return _dictionary()[section][name]
    except KeyError:
        raise ValueError('Unknown metadata identifier: ' + str(name)) from None


def class_labels():
    return _dictionary()['names'].copy()


def label_reference():
    return _dictionary()['source']
