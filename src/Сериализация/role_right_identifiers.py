"""Verified XML access-right names and native UUIDs, independent of row order."""
import json
import uuid
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType


def validate(data):
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1:
        raise ValueError('Unsupported access-right identifier profile')
    rights = data.get('rights')
    if not isinstance(rights, dict) or not rights:
        raise ValueError('Empty access-right identifier profile')
    for name, identifier in rights.items():
        if not isinstance(name, str) or not name or not name.isascii() or not name.isidentifier():
            raise ValueError('Invalid access-right name')
        try:
            valid = isinstance(identifier, str) and str(uuid.UUID(identifier)) == identifier and uuid.UUID(identifier).int != 0
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('Invalid access-right UUID: ' + name)
    if len(set(rights.values())) != len(rights):
        raise ValueError('Distinct access rights cannot share a UUID')
    return MappingProxyType(dict(rights))


@lru_cache(maxsize=1)
def profile():
    data = json.loads(Path(__file__).with_name('role_right_identifiers_851.json').read_text(encoding='utf-8'))
    return validate(data)


def right_id(name):
    """Return a verified UUID; unknown or differently cased names are errors."""
    if not isinstance(name, str) or name not in profile():
        raise ValueError('Unmapped access right: ' + str(name))
    return profile()[name]


@lru_cache(maxsize=1)
def inverse():
    return MappingProxyType({identifier: name for name, identifier in profile().items()})


def right_name(identifier):
    if not isinstance(identifier, str) or identifier not in inverse():
        raise ValueError('Unmapped access-right UUID: ' + str(identifier))
    return inverse()[identifier]
