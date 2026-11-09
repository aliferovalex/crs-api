"""Shared native commit assembly; XML converters supply object bodies.

Record order, graph order and external actions are protocol data, not inferred
from a metadata class. Full repository-version reading has a separate validator.
"""
import base64
import hashlib
import struct
import uuid
import zlib
from dataclasses import dataclass
import native_metadata as s


def content_version(raw, identifier=None):
    # Experimental client version, retained from the existing serializers.
    return (identifier or uuid.uuid4()).bytes_le + struct.pack('<I', zlib.crc32(raw))


def external_version():
    return uuid.uuid4().bytes_le + bytes(4)


def preserve_external_versions(docs,oid,owned=()):
    """Keep server streams by version; no payload is supplied for action zero."""
    refs=docs[0][11];count=int(s.val(refs[0]));cache=docs[2]
    if count<0 or len(refs)!=1+count*2 or len({s.val(n) for n in refs[1::2]})!=count:
        raise ValueError('Unsupported external object map')
    if any(not s.val(n).startswith(oid+'.') and s.val(n) not in owned for n in refs[1::2]):
        raise ValueError('Unsupported external object map')
    if s.render(cache)!='{0}' and (len(cache)!=count+1 or s.val(cache[0])!=str(count)
            or any(len(row)!=3 or s.val(row[0])!=s.val(refs[1+i*2]) or s.val(row[1])!=s.val(refs[2+i*2]) or s.val(row[2])!='1' for i,row in enumerate(cache[1:]))):
        raise ValueError('Unsupported external context')
    result=[]
    for index in range(count):
        slot=2+index*2;version=uuid.UUID(s.val(refs[slot])).bytes_le+bytes(4)
        refs[slot]=s.atom(base64.b64encode(version).decode())
        result.append(dict(name=s.val(refs[slot-1]),version=version.hex(),action=0))
    docs[2]=[s.atom(0)]
    return result


def commit_metadata(metadata, original, local):
    a=s.atom
    metadata[0],metadata[5],metadata[6]=a(6),a(4294967295),a(0)
    metadata[7],metadata[8]=a(base64.b64encode(original).decode()),a(base64.b64encode(local).decode())


def descriptor(metadata):
    m=metadata
    return [m[1],m[2],m[3],m[9],m[10],m[5],m[6],m[3],m[4],m[7],m[8],s.atom(0)]


def description(metadata, original, local):
    m=metadata
    return dict(id=s.val(m[1]),class_id=s.val(m[2]),name=s.val(m[9]),pos=int(s.val(m[10])),
                parent_id=s.val(m[3]),owner_id=s.val(m[4]),original=original.hex(),local=local.hex())


@dataclass
class ObjectRecord:
    object_id: str
    metadata: bytes
    body: bytes
    externals: tuple = ()  # Ordered (name, compressed payload) pairs.


def assemble(graph, objects):
    """Build one commit, preserving caller-supplied object and stream order."""
    objects=list(objects);seen=set();records=[];a=s.atom;manifest=[a(0),a(len(objects))]
    if len(graph)!=15 or not objects:raise ValueError('Invalid commit graph or empty object set')
    for obj in objects:
        oid=str(uuid.UUID(obj.object_id))
        if oid in seen:raise ValueError('Duplicate commit object')
        seen.add(oid);records.extend([obj.metadata,obj.body])
        manifest.extend([a(oid),a(hashlib.sha1(obj.metadata).hexdigest(),True),a(hashlib.sha1(obj.body).hexdigest(),True),a(len(obj.externals))])
        names=set()
        for name,data in obj.externals:
            if name in names:raise ValueError('Duplicate external stream')
            names.add(name);records.append(data)
            manifest.extend([a(name,True),a(hashlib.sha1(data).hexdigest(),True)])
    storage=s.storage(records,s.text_bytes([manifest]));s.validate_storage(storage)
    return s.SERIALIZER+s.compress(s.record(s.text_bytes([graph]))+bytes(4)+s.record(storage))


def child_map(pairs):
    pairs=list(pairs);result=[s.atom(len(pairs))]
    for oid,cls in pairs:result.extend([s.atom(oid),s.atom(cls)])
    return result
