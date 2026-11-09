"""Compiled object contents before the final repository graph is assembled."""
import base64
import copy
from typing import NamedTuple

import native_metadata as s
import native_streams


class ObjectContent(NamedTuple):
    docs: list
    body: bytes
    streams: list
    externals: list


def body_change(docs,saved,raw,oid):
    """Replace a verified definition while retaining every external stream."""
    import packet_builder
    refs={s.val(value) for value in docs[0][11][1::2]}
    externals=packet_builder.preserve_external_versions(docs,oid,native_streams.select(docs[0],refs))
    docs[0][15:17]=copy.deepcopy(saved[0][15:17]);docs[1]=copy.deepcopy(saved[1])
    return ObjectContent(docs,raw,[],externals)


def compiled_stream_changes(docs,saved,body,oid,before,after,names):
    """Reconcile already compiled streams; retain versions of untouched data."""
    import packet_builder
    import serialization_context
    import uuid
    previous=serialization_context.external_versions(docs[0][11])
    all_names=names|set(previous)
    owned=native_streams.select(docs[0],all_names)|native_streams.select(saved[0],all_names)
    if all_names!=owned:raise ValueError('Invalid compiled stream ownership')
    refs=[];cache=[];streams=[];externals=[]
    for name in sorted(set(previous)|names):
        old=before.get(name);new=after.get(name)
        if old is not None and name not in previous:raise ValueError('Source CF stream is absent from repository metadata')
        if name in previous and old is None:raise ValueError('Missing source compiled stream')
        if old!=new and name not in names:raise ValueError('Unrequested compiled stream change')
        if new is None:continue
        if old==new and name in previous:version=uuid.UUID(previous[name]).bytes_le+bytes(4);action=0
        else:
            version=packet_builder.external_version();action=1;streams.append((name,s.compress(new)))
            cache.append([s.atom(name,True),s.atom(base64.b64encode(version).decode()),s.atom(1)])
        refs.extend([s.atom(name,True),s.atom(base64.b64encode(version).decode())])
        externals.append(dict(name=name,version=version.hex(),action=action))
    docs[0][11]=[s.atom(len(externals))]+refs;docs[2]=[s.atom(len(cache))]+cache
    docs[0][15:17]=copy.deepcopy(saved[0][15:17]);docs[1]=copy.deepcopy(saved[1])
    return ObjectContent(docs,body,streams,externals)
