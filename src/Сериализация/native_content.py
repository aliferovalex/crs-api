"""Compiled object contents before the final repository graph is assembled."""
import base64
import copy
from typing import NamedTuple

import native_metadata as s


class ObjectContent(NamedTuple):
    docs: list
    body: bytes
    streams: list
    externals: list


class CreationContent(NamedTuple):
    objects: dict
    version_code: str


def body_change(docs,saved,raw,oid):
    """Replace a verified definition while retaining every external stream."""
    import packet_builder
    externals=packet_builder.preserve_external_versions(docs,oid)
    docs[0][15:17]=copy.deepcopy(saved[0][15:17]);docs[1]=copy.deepcopy(saved[1])
    return ObjectContent(docs,raw,[],externals)


def external_change(docs, saved, raw, name, payload, version):
    """Replace one stream while leaving object commit versions to the assembler."""
    a = s.atom
    docs[0][15:17] = copy.deepcopy(saved[0][15:17])
    docs[1] = copy.deepcopy(saved[1])
    if payload is None:
        docs[0][11]=[a(0)];docs[2]=[a(0)]
        return ObjectContent(docs,raw,[],[])
    encoded = base64.b64encode(version).decode()
    docs[0][11] = [a(1), a(name, True), a(encoded)]
    docs[2] = [a(1), [a(name, True), a(encoded), a(1)]]
    return ObjectContent(docs, raw, [(name, payload)],
                         [dict(name=name, version=version.hex(), action=1)])
