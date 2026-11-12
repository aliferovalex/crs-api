"""Indexed native storage on disk: bounded reads and streaming checksums."""
from collections.abc import Mapping
import hashlib
import os
from pathlib import Path
import struct
import uuid

import native_metadata as s
import resource_limits as limits


def publish_new(temporary,path):
    # Windows rename refuses an existing destination, including FAT/SMB paths.
    # POSIX rename replaces it, so use an atomic no-replace hard link there.
    if os.name=='nt':os.rename(str(temporary),str(path))
    else:os.link(str(temporary),str(path))


class FileStorage(Mapping):
    """Map a verified record hash to a bounded disk read, never a whole-file read."""
    def __init__(self, path):
        self.path = Path(path).resolve()
        initial=self.path.stat();self.fingerprint=(initial.st_size,initial.st_mtime_ns,initial.st_ino)
        size = initial.st_size
        if not 128 <= size <= limits.get('storage_bytes', s.MAX_STORAGE_BYTES):
            raise ValueError('Missing or oversized native storage file')
        with self.path.open('rb') as stream:
            header = stream.read(12)
            if header[:8] != s.HEADER[:8]: raise ValueError('Invalid storage file header')
            count = struct.unpack_from('<I', header, 8)[0]
            stream.seek(size-64); trailer = stream.read(64)
            if trailer[28:44] != s.EOF_MARKER: raise ValueError('Invalid storage file trailer')
            stream.seek(0); remaining = size-20; digest = hashlib.sha1()
            while remaining:
                chunk = stream.read(min(1024*1024, remaining))
                if not chunk: raise ValueError('Truncated storage file')
                digest.update(chunk); remaining -= len(chunk)
            if digest.digest() != trailer[44:]: raise ValueError('Storage file checksum mismatch')
            index_pos = size-struct.unpack_from('<Q', trailer)[0]
            if not 12 <= index_pos < size-64: raise ValueError('Invalid storage file index offset')
            stream.seek(index_pos); index = self._read_record(stream)
            if (stream.tell() != size-64 or len(index) != 52+28*count
                    or index[:12] != bytes.fromhex('11223344')+struct.pack('<II',2,count)
                    or index[-40:-20] != bytes(20)
                    or hashlib.sha1(index[:-20]).digest() != index[-20:]):
                raise ValueError('Invalid storage file index')
            indexed = {}; previous = None
            for pos in range(12,len(index)-40,28):
                key = index[pos:pos+20]; offset = struct.unpack_from('<Q',index,pos+20)[0]
                if previous is not None and key < previous or offset in indexed:
                    raise ValueError('Unsorted or duplicate storage file index')
                indexed[offset] = key; previous = key
            actual = {}; self.entries = {}; stream.seek(12)
            while stream.tell() < index_pos:
                offset = stream.tell(); length = self._length(stream)
                start = stream.tell()
                if start+length > index_pos: raise ValueError('Storage file record overlaps index')
                digest = hashlib.sha1(); remaining = length
                while remaining:
                    chunk = stream.read(min(1024*1024,remaining))
                    if not chunk: raise ValueError('Truncated storage file record')
                    digest.update(chunk); remaining -= len(chunk)
                key = digest.digest(); actual[offset] = key
                self.entries[key.hex()] = (start,length)
            if actual != indexed or len(actual) != count or trailer[8:28].hex() not in self.entries:
                raise ValueError('Storage file records do not match index')
        self.manifest = s.Parser(self[trailer[8:28].hex()].decode('utf-8-sig')).documents()[0]

    @staticmethod
    def _length(stream):
        raw = stream.read(8)
        if len(raw) != 8: raise ValueError('Truncated storage file record size')
        length = struct.unpack('<Q',raw)[0]
        if length > limits.get('record_bytes',s.MAX_BYTES): raise ValueError('Oversized storage file record: '+str(length)+' exceeds record_bytes '+str(limits.get('record_bytes',s.MAX_BYTES)))
        return length

    @classmethod
    def _read_record(cls, stream):
        length = cls._length(stream)
        if length > os.fstat(stream.fileno()).st_size-stream.tell():raise ValueError('Truncated storage file record')
        data = stream.read(length)
        if len(data) != length: raise ValueError('Truncated storage file record')
        return data

    def __getitem__(self, key):
        current=self.path.stat()
        if (current.st_size,current.st_mtime_ns,current.st_ino)!=self.fingerprint:
            raise ValueError('Storage file changed after validation')
        offset,length = self.entries[key]
        with self.path.open('rb') as stream:
            stream.seek(offset); raw = stream.read(length)
        if len(raw) != length or hashlib.sha1(raw).hexdigest() != key:
            raise ValueError('Storage file changed after validation')
        return raw

    def __iter__(self): return iter(self.entries)
    def __len__(self): return len(self.entries)
    def __contains__(self,key):return key in self.entries


def write(path, records, manifest):
    """Same framing/deduplication as s.storage, with one payload in memory."""
    path = Path(path)
    if path.exists(): raise ValueError('Storage output already exists')
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    offsets = {}; budget = limits.get('storage_bytes',s.MAX_STORAGE_BYTES)
    try:
        with temporary.open('x+b') as output:
            output.write(s.HEADER[:8]+bytes(4))
            def payloads():
                yield from records
                yield manifest() if callable(manifest) else manifest
            for payload in payloads():
                if len(payload) > limits.get('record_bytes',s.MAX_BYTES): raise ValueError('Oversized storage output record')
                digest = hashlib.sha1(payload).digest()
                if digest in offsets: continue
                offsets[digest] = output.tell()
                output.write(s.record(payload))
                if output.tell() > budget: raise ValueError('Storage output exceeds byte limit')
            count = len(offsets)
            index = bytes.fromhex('11223344')+struct.pack('<II',2,count)
            index += b''.join(digest+struct.pack('<Q',offset) for digest,offset in sorted(offsets.items()))+bytes(20)
            index += hashlib.sha1(index).digest()
            output.write(s.record(index)); output.write(struct.pack('<Q',len(index)+8+64))
            manifest_value=manifest() if callable(manifest) else manifest
            output.write(hashlib.sha1(manifest_value).digest()+s.EOF_MARKER)
            output.seek(8); output.write(struct.pack('<I',count)); output.flush()
        with temporary.open('ab') as output: output.write(bytes.fromhex(limits.file_digest(temporary,'sha1')))
        if temporary.stat().st_size > budget: raise ValueError('Storage output exceeds byte limit')
        FileStorage(temporary)
        publish_new(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)
    return dict(storage_file=str(path.resolve()),storage_sha256=limits.file_digest(path))
