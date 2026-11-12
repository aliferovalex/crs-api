"""Per-process resource policy shared by CLI, OneScript and Python workers."""
from functools import lru_cache
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path

MiB = 1024 * 1024
DEFAULTS = dict(message_bytes=256*MiB, storage_bytes=256*MiB, record_bytes=16*MiB,
                cf_bytes=256*MiB, image_bytes=512*MiB, export_file_bytes=16*MiB,
                export_total_bytes=128*MiB, export_files=65536, packet_bytes=256*MiB, module_bytes=8*MiB)
_scope=ContextVar('crs_resource_limits',default=None)


def validate(values):
    if not isinstance(values, dict) or set(values)-set(DEFAULTS):
        raise ValueError('Invalid resource limit names')
    if any(type(value) is not int or not 0 < value <= 2**63-1 for value in values.values()):
        raise ValueError('Resource limits must be positive integer values')
    return dict(values)


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate resource limit')
        result[key] = value
    return result


@lru_cache(maxsize=8)
def parse(raw):
    if len(raw.encode('utf-8')) > 65536: raise ValueError('Oversized resource policy')
    return validate(json.loads(raw, object_pairs_hook=unique))


@lru_cache(maxsize=8)
def read_policy_file(path):
    source=Path(path)
    if source.stat().st_size>65536:raise ValueError('Oversized resource policy')
    return source.read_text(encoding='utf-8-sig')


def overrides():
    if _scope.get() is not None:return _scope.get()
    raw = os.environ.get('CRS_LIMITS_JSON')
    if raw is None:
        path = os.environ.get('CRS_LIMITS_FILE')
        if path:
            raw = read_policy_file(path)
    return parse(raw) if raw is not None else {}


def get(name, default=None):
    return overrides().get(name, DEFAULTS[name] if default is None else default)


@contextmanager
def scope(values):
    token=_scope.set(validate(values))
    try:yield
    finally:_scope.reset(token)


def file_digest(path, algorithm='sha256'):
    import hashlib
    result = hashlib.new(algorithm)
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024*1024), b''): result.update(chunk)
    return result.hexdigest()
