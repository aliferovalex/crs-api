"""Read indexed streams from a native complete-version storage (duplicates allowed)."""
import base64,hashlib,struct,uuid
import native_metadata as s

# A complete configuration contains many individually bounded records.
MAX_STORAGE_BYTES = s.MAX_STORAGE_BYTES


def records(data):
    if len(data)<128 or len(data)>MAX_STORAGE_BYTES or data[:8]!=s.HEADER[:8]:raise ValueError('Unsupported version storage: bytes='+str(len(data)))
    if data[-36:-20]!=s.EOF_MARKER or hashlib.sha1(data[:-20]).digest()!=data[-20:]:raise ValueError('Version storage checksum mismatch')
    count=struct.unpack_from('<I',data,8)[0];start=len(data)-struct.unpack_from('<Q',data,len(data)-64)[0]
    if not 12<=start<len(data)-64:raise ValueError('Invalid version index offset')
    index,end=s.read_record(data,start)
    if end!=len(data)-64 or index[:12]!=bytes.fromhex('11223344')+struct.pack('<II',2,count) or len(index)!=52+28*count:raise ValueError('Invalid version index')
    if index[-40:-20]!=bytes(20) or hashlib.sha1(index[:-20]).digest()!=index[-20:]:raise ValueError('Version index checksum mismatch')
    payloads={};offsets={};pos=12
    while pos<start:
        offset=pos;payload,pos=s.read_record(data,pos)
        if pos>start:raise ValueError('Record overlaps version index')
        digest=hashlib.sha1(payload).digest();offsets[offset]=digest;payloads[digest.hex()]=payload
    entries={};previous=None
    for pos in range(12,len(index)-40,28):
        digest=index[pos:pos+20];offset=struct.unpack_from('<Q',index,pos+20)[0]
        if (previous is not None and digest<previous) or offset in entries:raise ValueError('Unsorted or duplicate version index entry')
        entries[offset]=digest;previous=digest
    if entries!=offsets or len(entries)!=count or data[-56:-36].hex() not in payloads:raise ValueError('Version index does not match records')
    return payloads,s.Parser(payloads[data[-56:-36].hex()].decode('utf-8-sig')).documents()[0]


def extract_many(data,object_ids=None,*,partial_externals=False):
    """Snapshots may intentionally carry only explicitly requested streams."""
    wanted=None if object_ids is None else {str(uuid.UUID(oid)) for oid in object_ids}
    payloads,manifest=records(data)
    if len(manifest)<2 or s.val(manifest[0])!='0':raise ValueError('Unsupported version manifest')
    pos=2;seen=set();found={}
    for _ in range(int(s.val(manifest[1]))):
        object_id=str(uuid.UUID(s.val(manifest[pos])));meta_hash=s.val(manifest[pos+1]);body_hash=s.val(manifest[pos+2]);count=int(s.val(manifest[pos+3]));pos+=4
        if object_id in seen or count<0 or count>1024 or meta_hash not in payloads or body_hash not in payloads:raise ValueError('Invalid version object manifest')
        seen.add(object_id);streams={}
        for _ in range(count):
            name=s.val(manifest[pos]);digest=s.val(manifest[pos+1]);pos+=2
            if name in streams or digest not in payloads:raise ValueError('Invalid external manifest')
            streams[name]=payloads[digest]
        if wanted is None or object_id in wanted:
            docs=s.Parser(payloads[meta_hash].decode('utf-8-sig')).documents();m=docs[0]
            if len(m)!=17 or s.val(m[0])!='5' or s.val(m[1])!=object_id:raise ValueError('Unsupported external object metadata')
            refs=m[11]
            expected={s.val(v) for v in refs[1::2]}
            matching=set(streams)<=expected if partial_externals else set(streams)==expected
            if len(refs)!=1+2*int(s.val(refs[0])) or not matching:raise ValueError('External versions/manifest mismatch')
            versions={s.val(refs[i]):uuid.UUID(s.val(refs[i+1])).bytes_le.hex()+'00000000' for i in range(1,len(refs),2)}
            found[object_id]=dict(data=base64.b64encode(payloads[body_hash]).decode(),object_id=object_id,class_id=s.val(m[2]),parent_id=s.val(m[3]),version_number=int(s.val(m[5])),
                original=uuid.UUID(s.val(m[7])).bytes_le.hex(),local=uuid.UUID(s.val(m[8])).bytes_le.hex(),
                externals=[dict(name=name,version=versions[name],data=base64.b64encode(blob).decode()) for name,blob in streams.items()])
    if pos!=len(manifest) or wanted is not None and set(found)!=wanted:raise ValueError('Object missing or malformed version manifest')
    return found


def extract(data,oid):
    oid=str(uuid.UUID(oid))
    return extract_many(data,{oid})[oid]


def from_request(request):
    return extract(s.decode_storage(request['storage'],'Oversized version input'),request['object_id'])


def main():
    from serializer_cli import run
    run(from_request)


if __name__=='__main__':main()
