"""Combine verified existing-object changes into one repository commit.

Object records and streams are read through the SHA1 manifest, never by physical
record order: native storage can deduplicate identical payloads.
"""
import metadata_context
import base64,copy,re,uuid
import native_metadata as s
import packet_builder as p
import external_data


def read_packet(encoded):
    if not isinstance(encoded,str) or len(encoded)>s.MAX_BYTES*2:raise ValueError('Oversized batch member')
    data=base64.b64decode(encoded,validate=True)
    if data[:18]!=s.SERIALIZER:raise ValueError('Invalid batch serializer signature')
    raw=s.inflate(data[18:]);graph_raw,pos=s.read_record(raw,0)
    if raw[pos:pos+4]!=bytes(4):raise ValueError('Invalid batch record separator')
    storage,end=s.read_record(raw,pos+4)
    if end!=len(raw):raise ValueError('Trailing batch transport data')
    s.validate_storage(storage);payloads,manifest=external_data.records(storage)
    graphs=s.Parser(graph_raw.decode('utf-8-sig')).documents()
    if len(graphs)!=1 or len(graphs[0])!=15:raise ValueError('Invalid batch graph')
    if len(manifest)<2 or s.val(manifest[0])!='0':raise ValueError('Invalid batch manifest')
    count=int(s.val(manifest[1]));pos=2;records=[];seen=set()
    if not 1<=count<=256:raise ValueError('Invalid batch object count')
    try:
        for _ in range(count):
            oid=metadata_context.guid(s.val(manifest[pos]));meta=payloads[s.val(manifest[pos+1])];body=payloads[s.val(manifest[pos+2])];n=int(s.val(manifest[pos+3]));pos+=4
            if oid in seen or not 0<=n<=1024:raise ValueError('Duplicate batch object or invalid external count')
            seen.add(oid);externals=[];names=set()
            for _ in range(n):
                name=s.val(manifest[pos]);blob=payloads[s.val(manifest[pos+1])];pos+=2
                if name in names:raise ValueError('Duplicate batch external stream')
                names.add(name);externals.append((name,blob))
            records.append(p.ObjectRecord(oid,meta,body,tuple(externals)))
    except (IndexError,KeyError):raise ValueError('Malformed batch manifest') from None
    if pos!=len(manifest):raise ValueError('Trailing batch manifest fields')
    return graphs[0],records


def version(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-fA-F]{40}',value):raise ValueError('Invalid batch object version')
    return bytes.fromhex(value)


def serialize(request):
    members=request['packets']
    if not isinstance(members,list) or not 1<=len(members)<=256:raise ValueError('Batch needs 1..256 change packets')
    uuid.UUID(request['repository_version']);graphs=[];records=[];descriptions=[];externals=[];features=[];seen=set();stream_names=set()
    for member in members:
        graph,entries=read_packet(member['data'])
        # Existing single-object preparations are canonical change_graph commits.
        # Creation/deletion need a final shared owner body, not graph concatenation.
        if len(entries)!=1:raise ValueError('Batch member must change one existing object')
        record=entries[0];oid=record.object_id
        if oid in seen:raise ValueError('Duplicate batch changed object')
        seen.add(oid);docs=s.Parser(record.metadata.decode('utf-8-sig')).documents()
        if len(docs)!=3 or len(docs[0])!=17 or s.val(docs[0][0])!='6' or s.val(docs[0][1])!=oid:raise ValueError('Invalid batch commit metadata')
        m=docs[0];pairs=metadata_context.children(m)
        if len(graph[7])!=3:raise ValueError('Unsupported batch external graph')
        expected=p.change_graph(m,p.child_map(pairs),externals=graph[7][2])
        if s.render(graph)!=s.render(expected):raise ValueError('Batch member is not a canonical existing-object change')
        ds=member['descriptions']
        if len(ds)!=1:raise ValueError('Batch member descriptions differ from records')
        d=ds[0];original=version(d['original']);local=version(d['local'])
        if d!=p.description(m,original,local):raise ValueError('Batch description differs from metadata')
        if base64.b64decode(s.val(m[7]),validate=True)!=original or base64.b64decode(s.val(m[8]),validate=True)!=local or original==local:
            raise ValueError('Batch source/local versions differ from metadata')
        stream_versions={s.val(m[11][i]):base64.b64decode(s.val(m[11][i+1]),validate=True).hex() for i in range(1,len(m[11]),2)}
        if len(m[11])!=1+2*int(s.val(m[11][0])) or len(stream_versions)!=int(s.val(m[11][0])):raise ValueError('Invalid batch external metadata')
        ext=member.get('externals',[]);names=set();changed=set()
        for item in ext:
            name=item['name']
            if item['object_id']!=oid or name in names or name in stream_names or item['action'] not in (0,1) or version(item['version']).hex()!=stream_versions.get(name):
                raise ValueError('Batch external descriptor differs from metadata')
            names.add(name);stream_names.add(name)
            if item['action']==1:changed.add(name)
        if names!=set(stream_versions) or changed!={name for name,_ in record.externals}:raise ValueError('Batch external payload/actions mismatch')
        cache=docs[2]
        if len(cache)!=len(changed)+1 or s.val(cache[0])!=str(len(changed)) or {s.val(row[0]) for row in cache[1:]}!=changed:
            raise ValueError('Batch external cache differs from payloads')
        for row in cache[1:]:
            if len(row)!=3 or s.val(row[2])!='1' or base64.b64decode(s.val(row[1]),validate=True).hex()!=stream_versions[s.val(row[0])]:raise ValueError('Invalid batch external cache version')
        graphs.append(graph);records.append(record);descriptions.append(copy.deepcopy(d));externals.extend(copy.deepcopy(ext))
        features.extend(copy.deepcopy(member.get('features',[])))
    a=s.atom;combined=[[a(0)] for _ in range(15)]
    for index in range(10):
        if index==6:continue
        combined[index]=[a(sum(int(s.val(graph[index][0])) for graph in graphs))]
        for graph in graphs:combined[index].extend(copy.deepcopy(graph[index][1:]))
    combined[10]=a(0);combined[12]=a(0);combined[14]=[a(1),[a(0)]]
    # Individual converters retain their source and reference validation. Mixing
    # removals/creations requires a final target graph and is handled separately.
    payload=p.assemble(combined,records)
    return dict(data=base64.b64encode(payload).decode(),descriptions=descriptions,externals=externals,features=features,
                repository=request['repository'],platform=request['platform'],repository_version=request['repository_version'])


if __name__=='__main__':
    from serializer_cli import run
    run(serialize)
