"""Shared reading of one snapshot and its matching updateInfo metadata.

Complete-version storage (which can contain duplicate physical records) remains
the responsibility of external_data, not this single-snapshot reader.
"""
import base64,re,uuid
from dataclasses import dataclass
import metadata_serializer as s


def decode(encoded,error):
    if not isinstance(encoded,str) or len(encoded)>s.MAX_BYTES*2:raise ValueError(error)
    return base64.b64decode(encoded,validate=True)


@dataclass
class SnapshotContext:
    saved: list
    docs: list
    data: bytes
    context: bytes

    @property
    def metadata(self):return self.docs[0]


def read(request,oid,size_error='Oversized snapshot input',mismatch_error='Snapshot/context mismatch',snapshot_key='snapshot'):
    snapshot=decode(request[snapshot_key],size_error);context=decode(request['context'],size_error)
    s.validate_storage(snapshot);s.validate_storage(context)
    raw,pos=s.read_record(snapshot,12);body,pos=s.read_record(snapshot,pos)
    saved=s.Parser(raw.decode('utf-8-sig')).documents();docs=s.context_metadata(context,oid)
    if (len(saved)!=3 or len(docs)!=3 or len(saved[0])!=17 or len(docs[0])!=17
            or s.val(saved[0][0])!='5' or s.val(docs[0][0])!='5'
            or [s.render(v) for v in saved[0][:12]]!=[s.render(v) for v in docs[0][:12]]):raise ValueError(mismatch_error)
    return SnapshotContext(saved,docs,body,context)


def original_version(value,metadata,error='Source version mismatch'):
    if not isinstance(value,str):raise ValueError(error)
    value=value.lower()
    if not re.fullmatch('[0-9a-f]{40}',value) or uuid.UUID(s.val(metadata[7])).bytes_le.hex()!=value[:32]:raise ValueError(error)
    return value
