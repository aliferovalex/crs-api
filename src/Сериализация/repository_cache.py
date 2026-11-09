"""Incremental native CF cache. Never compile XML or modify a repository here."""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from xml.etree import ElementTree as E

import external_data
import ibcmd_backend
import metadata_context
import native_metadata as s
import packet_builder
import serialization_context
import platform_profiles
import native_streams

SERVICE={'root','version','versions'}


def service_versions(image,records):
    values={oid:row['local'] for oid,row in records.items()}
    for row in records.values():values.update(row['externals'])
    for key in ('root','version'):values[key]=str(uuid.uuid5(uuid.NAMESPACE_OID,key+':'+digest(image[key])))
    anchor=digest(json.dumps(values,sort_keys=True).encode())
    values['versions']=str(uuid.uuid5(uuid.NAMESPACE_OID,'versions:'+anchor))
    values['']=str(uuid.uuid5(uuid.NAMESPACE_OID,'header:'+anchor))
    atoms=[s.atom(1),s.atom(len(values))]
    for key in sorted(values):atoms.extend([s.atom(key,True),s.atom(values[key])])
    return s.text_bytes([atoms])


def digest(raw):return hashlib.sha256(raw).hexdigest()


def inventory(context):
    objects=metadata_context.context_objects(context)
    roots=[oid for oid,docs in objects.items() if s.val(docs[0][3])==s.ZERO]
    if len(roots)!=1:raise ValueError('Cache requires exactly one configuration root')
    records={};names=set();identities={}
    for oid,docs in objects.items():
        for value in native_streams.identities(docs[0]):
            if value in identities:raise ValueError('Ambiguous cache stream owner identity')
            identities[value]=oid
    for oid,docs in objects.items():
        m=docs[0];streams=serialization_context.external_versions(m[11])
        if native_streams.select(m,streams)!=set(streams) or names.intersection(streams):raise ValueError('Invalid cache stream ownership')
        if oid in names:raise ValueError('Duplicate cache entry')
        names.update(streams);names.add(oid)
        records[oid]=dict(local=metadata_context.guid(s.val(m[8])),original=metadata_context.guid(s.val(m[7])),
                          class_id=s.val(m[2]),parent_id=s.val(m[3]),externals=streams)
    return roots[0],records,objects


def versions(raw):
    docs=s.Parser(raw.decode('utf-8-sig')).documents()
    if len(docs)!=1:raise ValueError('Invalid CF versions documents')
    row=docs[0]
    if len(row)<4 or s.val(row[0])!='1' or len(row)!=2+2*int(s.val(row[1])):raise ValueError('Invalid CF versions layout')
    result={}
    for i in range(2,len(row),2):
        name=s.val(row[i])
        if name in result or not row[i].quoted:raise ValueError('Duplicate/invalid CF version entry')
        result[name]=metadata_context.guid(s.val(row[i+1]))
    if '' not in result:raise ValueError('Missing CF versions header')
    return result


def validate_image(image,root,records):
    expected={oid:row['local'] for oid,row in records.items()}
    for row in records.values():expected.update(row['externals'])
    if set(image)!=set(expected)|SERVICE:raise ValueError('CF inventory differs from repository context')
    v=versions(image['versions'])
    if set(v)!=set(image)|{''} or any(v.get(key)!=value for key,value in expected.items()):raise ValueError('CF versions differ from repository context')
    root_doc=s.Parser(image['root'].decode('utf-8-sig')).documents()
    if len(root_doc)!=1 or len(root_doc[0])!=2 or s.val(root_doc[0][0])!='2' or s.val(root_doc[0][1])!=root:
        raise ValueError('CF root differs from repository context')


def identity(request):
    if 'repository_info' in request:
        text=request['repository_info']
        if len(text)>s.MAX_BYTES or '<!DOCTYPE' in text.upper():raise ValueError('Invalid repository information')
        root=E.fromstring(text);q='{'+s.NS+'}'
        for node in root.iter():
            if node.tag in (q+'exc',q+'exception') and (node.text or '').strip():raise ValueError('Repository information failed')
        node=root.find(q+'info/'+q+'info/'+q+'depotID')
        if node is None:raise ValueError('Missing repository identity')
        return metadata_context.guid(node.get('value'))
    return metadata_context.guid(request['repository_id'])


class Cache:
    def __init__(self,directory):self.directory=Path(directory).resolve()

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        lock=self.directory/'write.lock'
        try:fd=os.open(str(lock),os.O_WRONLY|os.O_CREAT|os.O_EXCL)
        except FileExistsError:raise ValueError('Cache update is already running; inspect write.lock after a crashed process') from None
        try:
            os.write(fd,str(os.getpid()).encode());os.close(fd)
            yield
        finally:lock.unlink()

    def load(self):
        if not (self.directory/'current.json').is_file():raise ValueError('Initialize the repository cache first')
        pointer=json.loads((self.directory/'current.json').read_text(encoding='utf-8'))
        generation=pointer['generation']
        if not re.fullmatch('[0-9a-f]{32}',generation):raise ValueError('Invalid cache generation')
        folder=self.directory/'generations'/generation
        raw=(folder/'repository-state.json').read_bytes()
        if digest(raw)!=pointer['state_sha256']:raise ValueError('Cache state checksum mismatch')
        state=json.loads(raw)
        path=folder/'base.cf'
        if state['schema']!=1 or state['generation']!=generation or digest(path.read_bytes())!=state['cf_sha256']:raise ValueError('Cache CF checksum mismatch')
        image=ibcmd_backend.read_cf(path)
        if {key:digest(raw) for key,raw in image.items()}!=state['entries']:raise ValueError('Cache entry checksum mismatch')
        validate_image(image,state['root_id'],state['objects'])
        return state,image,path

    def publish(self,image,state):
        generation=uuid.uuid4().hex;folder=self.directory/'generations'/generation
        folder.mkdir(parents=True)
        path=folder/'base.cf';ibcmd_backend.write_cf(path,image)
        state=dict(state,schema=1,generation=generation,cf_sha256=digest(path.read_bytes()),entries={key:digest(raw) for key,raw in image.items()})
        raw=(json.dumps(state,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8')
        (folder/'repository-state.json').write_bytes(raw)
        pointer=dict(generation=generation,state_sha256=digest(raw))
        temporary=self.directory/('current-'+generation+'.tmp')
        temporary.write_text(json.dumps(pointer),encoding='utf-8')
        os.replace(str(temporary),str(self.directory/'current.json'))
        return dict(base_cf=str(path),generation=generation,repository_version=state['repository_version'],repository_id=state['repository_id'],root_id=state['root_id'])

    def initialize(self,request):
        with self.locked():
            if (self.directory/'current.json').exists():raise ValueError('Cache already initialized')
            root,records,_=inventory(request['context']);image=ibcmd_backend.read_cf(request['seed_cf'])
            validate_image(image,root,records)
            state=dict(repository_id=identity(request),platform=request['platform'],root_id=root,objects=records,
                       repository_version=metadata_context.guid(request['repository_version']))
            return self.publish(image,state)

    def bootstrap(self,request):
        """Build the first CF from verified native repository data, without XML."""
        with self.locked():
            if (self.directory/'current.json').exists():raise ValueError('Cache already initialized')
            version=metadata_context.guid(request['repository_version'])
            if request['repository_version_after']!=version:raise ValueError('Repository changed during initial download')
            root,records,objects=inventory(request['context'])
            profiles=json.loads(Path(__file__).with_name('cf_service_profiles.json').read_text(encoding='utf-8'))
            profile=profiles.get(platform_profiles.profile(request['platform']))
            if profile is None:raise ValueError('No initial CF service profile for this platform; supply seed_cf')
            data=serialization_context.decode(request['storage'],'Oversized initial repository data')
            received=external_data.extract_many(data,set(objects));image={}
            for oid,row in received.items():
                m=objects[oid][0];expected=records[oid]
                if (row['class_id'],row['parent_id'],row['version_number'],row['original'],row['local'])!=(expected['class_id'],expected['parent_id'],int(s.val(m[5])),uuid.UUID(expected['original']).bytes_le.hex(),uuid.UUID(expected['local']).bytes_le.hex()):
                    raise ValueError('Initial repository data/context mismatch: '+oid)
                actual={entry['name']:entry['version'] for entry in row['externals']}
                wanted={name:uuid.UUID(value).bytes_le.hex()+'00000000' for name,value in expected['externals'].items()}
                if actual!=wanted:raise ValueError('Initial stream versions differ from context')
                image[oid]=s.inflate(base64.b64decode(row['data'],validate=True))
                for entry in row['externals']:image[entry['name']]=s.inflate(base64.b64decode(entry['data'],validate=True))
            def native(value):return [native(item) for item in value] if isinstance(value,list) else s.atom(value)
            image['root']=('﻿{'+str(profile['root_format'])+','+root+',}').encode('utf-8')
            image['version']=s.text_bytes([native(profile['version'])])
            image['versions']=service_versions(image,records)
            validate_image(image,root,records)
            state=dict(repository_id=identity(request),platform=request['platform'],root_id=root,objects=records,repository_version=version)
            return self.publish(image,state)

    def plan(self,request):
        state,image,path=self.load();root,records,_=inventory(request['context'])
        if (identity(request),request['platform'],root)!=(state['repository_id'],state['platform'],state['root_id']):raise ValueError('Cache belongs to another repository, platform or root')
        old=state['objects'];new=set(records)-set(old);removed=sorted(set(old)-set(records))
        bodies=sorted(oid for oid,row in records.items() if oid in new or old[oid]['local']!=row['local'])
        streams={}
        for oid,row in records.items():
            if oid in old and (row['class_id'],row['parent_id'])!=(old[oid]['class_id'],old[oid]['parent_id']):raise ValueError('Existing cache object changed class or parent')
            changed=[dict(name=name,version=uuid.UUID(version).bytes_le.hex()+'00000000') for name,version in row['externals'].items() if old.get(oid,{}).get('externals',{}).get(name)!=version]
            if changed:streams[oid]=changed
        wanted=set(records)|{name for row in records.values() for name in row['externals']}|SERVICE
        return dict(generation=state['generation'],context_sha256=digest(base64.b64decode(request['context'],validate=True)),
                    body_ids=bodies,new_ids=sorted(new),removed_ids=removed,removed_entries=sorted(set(image)-wanted),
                    fetch=[dict(object_id=oid,streams=streams.get(oid,[])) for oid in sorted(set(bodies)|set(streams))],
                    repository_version=metadata_context.guid(request['repository_version']),base_cf=str(path))

    def update(self,request):
        with self.locked():
            plan=self.plan(request)
            if request['generation']!=plan['generation']:raise ValueError('Cache changed after planning')
            if request['context_sha256']!=plan['context_sha256']:raise ValueError('Repository context changed after planning')
            if request['repository_version_after']!=plan['repository_version']:raise ValueError('Repository changed during cache update')
            state,image,path=self.load();root,records,objects=inventory(request['context'])
            expected={row['object_id'] for row in plan['fetch']};snapshots=request.get('snapshots',{})
            if set(snapshots)!=expected:raise ValueError('Cache update requires exactly the planned snapshots')
            changed={}
            for row in plan['fetch']:
                oid=row['object_id'];encoded=snapshots[oid]
                frame=serialization_context.read(dict(context=request['context'],snapshot=encoded),oid)
                result=external_data.extract_many(base64.b64decode(encoded,validate=True),{oid},partial_externals=True)[oid]
                wanted={item['name'] for item in row['streams']}
                if {item['name'] for item in result['externals']}!=wanted:raise ValueError('Server returned missing or unrequested cache streams')
                body=s.inflate(frame.data)
                if oid in plan['body_ids']:changed[oid]=body
                elif body!=image[oid]:raise ValueError('Body changed without a changed repository version')
                for item in result['externals']:
                    version=records[oid]['externals'][item['name']]
                    if item['version']!=uuid.UUID(version).bytes_le.hex()+'00000000':raise ValueError('Cache stream version mismatch')
                    changed[item['name']]=s.inflate(base64.b64decode(item['data'],validate=True))
            image.update(changed)
            for name in plan['removed_entries']:image.pop(name)
            # Keep all payload records supplied by the server; only service
            # versions are assembled here, without metadata property writers.
            previous=versions(image['versions']);values={oid:row['local'] for oid,row in records.items()}
            for row in records.values():values.update(row['externals'])
            for name in SERVICE|{''}:values[name]=previous[name]
            if changed or plan['removed_entries']:
                payload_digest=b''.join(key.encode()+b'\0'+digest(raw).encode() for key,raw in sorted(image.items()) if key!='versions')
                revision_map=json.dumps({key:value for key,value in values.items() if key not in ('','versions')},sort_keys=True).encode()
                anchor=digest(payload_digest+b'\0'+revision_map)
                values['versions']=str(uuid.uuid5(uuid.NAMESPACE_OID,anchor))
                values['']=str(uuid.uuid5(uuid.NAMESPACE_OID,'header:'+anchor))
                atoms=[s.atom(1),s.atom(len(values))]
                for key in sorted(values):atoms.extend([s.atom(key,True),s.atom(values[key])])
                image['versions']=s.text_bytes([atoms])
            validate_image(image,root,records)
            if not changed and not plan['removed_entries'] and state['objects']==records and state['repository_version']==plan['repository_version']:
                result=dict(base_cf=str(path),generation=state['generation'],repository_version=state['repository_version'])
            else:
                state.update(objects=records,repository_version=plan['repository_version'])
                result=self.publish(image,state)
            return dict(result,repository_id=state['repository_id'],root_id=state['root_id'],fetched_ids=sorted(expected),changed_body_ids=plan['body_ids'],removed_ids=plan['removed_ids'],
                        fetched_streams=sorted(name for name in changed if name not in records))

    def source(self,request):
        """Build the source snapshots/storage locally; never request a full version."""
        state,image,_=self.load();root,records,objects=inventory(request['context'])
        if (identity(request),request['platform'],request['repository_version'],root,records)!=(state['repository_id'],state['platform'],state['repository_version'],state['root_id'],state['objects']):
            raise ValueError('Refresh cache before preparing source snapshots')
        wanted=request['snapshot_ids']
        if len(set(wanted))!=len(wanted) or not set(wanted)<=set(objects):raise ValueError('Invalid cached snapshot selection')
        payloads=[];manifest=[s.atom(0),s.atom(len(objects))];snapshots=[]
        for oid,docs in objects.items():
            meta=s.text_bytes(docs);body=s.compress(image[oid]);payloads.extend([meta,body])
            streams=records[oid]['externals']
            header=[s.atom(oid),s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(body).hexdigest(),True)]
            manifest.extend(header+[s.atom(len(streams))])
            for name in streams:
                raw=s.compress(image[name]);payloads.append(raw)
                manifest.extend([s.atom(name,True),s.atom(hashlib.sha1(raw).hexdigest(),True)])
            if oid in wanted:
                snapshot=s.storage([meta,body],s.text_bytes([[s.atom(0),s.atom(1)]+header+[s.atom(0)]]))
                original=uuid.UUID(records[oid]['original']).bytes_le+bytes(4)
                local=uuid.UUID(records[oid]['local']).bytes_le+bytes(4)
                snapshots.append(dict(object_id=oid,snapshot=base64.b64encode(snapshot).decode(),
                    description=packet_builder.description(docs[0],original,local),
                    version_number=int(s.val(docs[0][5])),self_version_number=int(s.val(docs[0][6]))))
        storage=s.storage(payloads,s.text_bytes([manifest]))
        if len(storage)>external_data.MAX_STORAGE_BYTES:raise ValueError('Cached version storage exceeds protocol reader limit')
        return dict(snapshots=snapshots,storage=base64.b64encode(storage).decode(),repository_version=state['repository_version'])


def run(request):
    cache=Cache(request['cache_directory'])
    if request['mode']=='initialize':return cache.initialize(request)
    if request['mode']=='bootstrap':return cache.bootstrap(request)
    if request['mode']=='plan':return cache.plan(request)
    if request['mode']=='update':return cache.update(request)
    if request['mode']=='source':return cache.source(request)
    raise ValueError('Unknown repository cache mode')


if __name__=='__main__':
    from serializer_cli import run as cli
    cli(run)
