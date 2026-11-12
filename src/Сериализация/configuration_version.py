"""Read the configuration's Version for commit history, never from history labels."""
import base64
import zlib
import uuid
import external_data
import metadata_identifiers
import native_configuration_reader as reader
import native_metadata as s
import resource_limits as limits


def from_body(body,object_id,platform):
    docs=s.Parser(body.decode('utf-8-sig')).documents()
    return reader.configuration_version(docs,object_id,platform)


def read(request):
    oid=request['object_id'];mode=request['mode']
    if mode not in ('snapshot','packet'):raise ValueError('Unknown configuration version source')
    if mode=='snapshot':storage=s.decode_storage(request['data'])
    else:
        budget=limits.get('packet_bytes')
        encoded=request['data']
        if not isinstance(encoded,str) or len(encoded)>4*((budget+2)//3):raise ValueError('Oversized commit packet')
        data=base64.b64decode(encoded,validate=True)
        if len(data)>budget or not data.startswith(s.SERIALIZER):raise ValueError('Invalid commit packet header')
        decoder=zlib.decompressobj(-15);raw=decoder.decompress(data[len(s.SERIALIZER):],budget+1)
        if len(raw)>budget or not decoder.eof or decoder.unused_data:raise ValueError('Invalid or oversized commit packet')
        _,pos=s.read_record(raw,0)
        if raw[pos:pos+4]!=bytes(4):raise ValueError('Invalid commit graph separator')
        storage,end=s.read_record(raw,pos+4,budget=limits.get('storage_bytes'))
        if end!=len(raw):raise ValueError('Trailing commit packet data')
    payloads,manifest=external_data.records(storage)
    if len(manifest)<2 or s.val(manifest[0])!='0':raise ValueError('Invalid configuration version manifest')
    pos=2;found=None;seen=set()
    for _ in range(int(s.val(manifest[1]))):
        identity=s.val(manifest[pos]);meta_hash=s.val(manifest[pos+1]);body_hash=s.val(manifest[pos+2])
        count=int(s.val(manifest[pos+3]));pos+=4
        if identity in seen or count<0 or pos+count*2>len(manifest):raise ValueError('Invalid configuration version manifest')
        seen.add(identity);pos+=count*2
        if identity!=oid:continue
        docs=s.Parser(payloads[meta_hash].decode('utf-8-sig')).documents();m=docs[0]
        if (len(m)!=17 or s.val(m[0])!=('5' if mode=='snapshot' else '6') or s.val(m[1])!=oid
                or s.val(m[2])!=metadata_identifiers.class_id('Configuration') or s.val(m[3])!=s.ZERO):
            raise ValueError('Configuration version source is not the repository root')
        if mode=='snapshot':
            for name,index in (('original',7),('local',8)):
                if request[name][:32]!=uuid.UUID(s.val(m[index])).bytes_le.hex():
                    raise ValueError('Configuration version snapshot differs from root descriptor')
        found=from_body(s.inflate(payloads[body_hash]),oid,request['platform'])
    if pos!=len(manifest) or found is None:raise ValueError('Configuration root is absent from version source')
    return dict(version_code=found,object_id=oid)


if __name__=='__main__':
    from serializer_cli import run
    run(read)
