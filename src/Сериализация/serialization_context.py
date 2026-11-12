"""Shared reading of one snapshot and its matching updateInfo metadata.

Complete-version storage (which can contain duplicate physical records) remains
the responsibility of external_data, not this single-snapshot reader.
"""
import metadata_context
import re,uuid
from dataclasses import dataclass
import native_metadata as s


def decode(encoded,error):
    return s.decode_storage(encoded,error)


def has_storage(request):return 'storage' in request or 'storage_file' in request


def storage(request,error='Invalid version storage'):
    """File and base64 inputs have the same checked record interface."""
    if 'storage_file' in request:
        from native_storage_file import FileStorage
        cached=request.get('_storage_file_reader')
        if cached is None:
            cached=FileStorage(request['storage_file']);request['_storage_file_reader']=cached
        return cached
    return decode(request['storage'],error)


@dataclass
class SnapshotContext:
    saved: list
    docs: list
    data: bytes
    context: bytes

    @property
    def metadata(self):return self.docs[0]


def external_versions(group):
    """Source stream versions form a map; server record order is not stable."""
    if (not isinstance(group,list) or not group or not isinstance(group[0],s.Atom)
            or not s.val(group[0]).isdecimal() or len(group)!=1+int(s.val(group[0]))*2):
        raise ValueError('Invalid external version map')
    result={}
    for index in range(1,len(group),2):
        name,version=group[index:index+2]
        if not isinstance(name,s.Atom) or not isinstance(version,s.Atom) or not s.val(name) or s.val(name) in result:
            raise ValueError('Invalid or duplicate external stream')
        result[s.val(name)]=str(uuid.UUID(s.val(version)))
    return result


def validate_metadata(saved,current,oid,error='Snapshot/context mismatch'):
    """Compare source metadata without exposing object contents in diagnostics."""
    if (len(saved)!=17 or len(current)!=17
            or s.val(saved[0])!='5' or s.val(current[0])!='5'):
        raise ValueError(error+': object='+oid+'; invalid metadata shape')
    fields=[str(index) for index in range(11) if s.render(saved[index])!=s.render(current[index])]
    try:
        if external_versions(saved[11])!=external_versions(current[11]):fields.append('11')
    except ValueError:
        raise ValueError(error+': object='+oid+'; invalid external version map') from None
    if fields:raise ValueError(error+': object='+oid+'; fields='+','.join(fields))


def read(request,oid,size_error='Oversized snapshot input',mismatch_error='Snapshot/context mismatch',snapshot_key='snapshot'):
    snapshot=decode(request[snapshot_key],size_error);context=decode(request['context'],size_error)
    s.validate_storage(snapshot);s.validate_storage(context)
    raw,pos=s.read_record(snapshot,12);body,pos=s.read_record(snapshot,pos)
    saved=s.Parser(raw.decode('utf-8-sig')).documents();docs=metadata_context.context_metadata(context,oid)
    if len(saved)!=3 or len(docs)!=3:raise ValueError(mismatch_error+': object='+oid+'; invalid document count')
    validate_metadata(saved[0],docs[0],oid,mismatch_error)
    return SnapshotContext(saved,docs,body,context)


def original_version(value,metadata,error='Source version mismatch'):
    if not isinstance(value,str):raise ValueError(error)
    value=value.lower()
    if not re.fullmatch('[0-9a-f]{40}',value) or uuid.UUID(s.val(metadata[7])).bytes_le.hex()!=value[:32]:raise ValueError(error)
    return value
