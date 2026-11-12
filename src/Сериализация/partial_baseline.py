"""File-backed, explicitly incomplete XML views over an immutable complete CF.

Exporter dispositions describe representation, not permission to compile an
object. A sparse working copy never implies deletion of files not checked out.
Whole-configuration compilation/bootstrap is deliberately unavailable here.
"""
import json
import mmap
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import uuid
from xml.etree import ElementTree as ET

import configuration_export as export
import cf_container
from export_snapshot import expected_versions, version_map
import ibcmd_backend
import native_metadata
import repository_cache
import resource_limits as limits

MARKER='.crs-partial.json'
IO_WORKERS=32


def key(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{32}',value):
        raise ValueError('Invalid partial baseline identity')
    return value


def relative(value):
    if (not isinstance(value,str) or not value or '\\' in value or ':' in value
            or '\0' in value or PurePosixPath(value).is_absolute()
            or any(p in ('','.','..') for p in value.split('/'))):
        raise ValueError('Invalid partial export path')
    return value


def json_file(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')


def scan(directory):
    """Hash one file at a time; a large export must not become a bytes dict."""
    base=Path(directory).resolve();files={};total=0
    if not base.is_dir():raise ValueError('Missing partial export directory')
    def paths(directory):
        # Refuse links/reparse points using cached scandir attributes. Repeated
        # realpath walks on every Windows directory dominate a 100k-file scan.
        with os.scandir(directory) as listing:children=sorted(listing,key=lambda item:item.name)
        for item in children:
            if directory==base and item.name in ('.git','.gitignore','.crs-cache'):continue
            path=Path(item.path)
            attributes=item.stat(follow_symlinks=False)
            if item.is_symlink() or getattr(attributes,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400):
                raise ValueError('Partial export contains a symlink or reparse point')
            if item.is_dir(follow_symlinks=False):
                yield from paths(path)
            elif item.is_file(follow_symlinks=False):yield path,attributes
            else:raise ValueError('Unsupported partial export filesystem entry')
    def hashed(item):
        name,path,before=item
        checksum=limits.file_digest(path);after=path.stat()
        # Windows DirEntry.stat may report inode=0; compare identities only
        # where the directory listing actually supplied one.
        if ((before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns)
                or before.st_ino and before.st_ino!=after.st_ino):
            raise ValueError('Partial export changed while reading: '+name)
        return name,dict(bytes=before.st_size,sha256=checksum)
    count=0;batch=[]
    # Bounded batches avoid 100k futures and overlap small-file open latency.
    # Worker hashes need no resource policy: limits are checked in this thread.
    with ThreadPoolExecutor(max_workers=IO_WORKERS) as pool:
        for path,before in paths(base):
            name=relative(path.relative_to(base).as_posix())
            if name==MARKER:continue
            total+=before.st_size;count+=1
            if (count>limits.get('export_files',65536)
                    or before.st_size>limits.get('export_file_bytes',16*1024*1024)
                    or total>limits.get('export_total_bytes',128*1024*1024)):
                raise ValueError('Partial export exceeds file/count/total limits')
            batch.append((name,path,before))
            if len(batch)==512:
                files.update(pool.map(hashed,batch));batch=[]
        files.update(pool.map(hashed,batch))
    return files


def metadata(path,oid,checksum=None):
    raw=path.read_bytes()
    if checksum is not None and repository_cache.digest(raw)!=checksum:
        raise ValueError('Partial metadata changed after hashing: '+oid)
    if b'<!DOCTYPE' in raw.upper():raise ValueError('Partial export DOCTYPE is unsupported')
    top=ET.fromstring(raw)
    if top.tag!=export.Q+'MetaDataObject' or len(top)!=1 or top[0].get('uuid')!=oid:
        raise ValueError('Partial metadata identity differs from native owner: '+oid)
    return top[0]


def native_versions(cf,state):
    """Read only CF service records, even when the exporter omitted dump info."""
    wanted={oid:row['local'] for oid,row in state['objects'].items()}
    for row in state['objects'].values():wanted.update(row['externals'])
    # The container reader seeks to the end to validate every block. A mapped
    # read-only view avoids flushing/reloading a buffered file for each seek;
    # mapping the CF does not materialize its decoded bodies in memory.
    with cf.open('rb') as backing,mmap.mmap(backing.fileno(),0,access=mmap.ACCESS_READ) as source:
        offset=ibcmd_backend.primary_container_offset(source)
        container=cf_container.detect_format(source,offset);container.read(source,offset)
        if set(container.files)!=set(wanted)|repository_cache.SERVICE:
            raise ValueError('Partial source CF inventory differs from native cache')
        versions=repository_cache.versions(native_metadata.inflate(b''.join(container.files['versions'].data)))
        root=native_metadata.Parser(native_metadata.inflate(b''.join(container.files['root'].data)).decode('utf-8-sig')).documents()
        if (set(versions)!=set(container.files)|{''} or any(versions.get(k)!=v for k,v in wanted.items())
                or len(root)!=1 or len(root[0])!=2 or native_metadata.val(root[0][0])!='2'
                or native_metadata.val(root[0][1])!=state['root_id']):
            raise ValueError('Partial source CF versions/root differ from native cache')
    return wanted


def coverage(state,cf,xml,report,*,index_file=None):
    """Bind the complete storage report, XML version map and native cache."""
    if (not isinstance(report,dict) or report.get('schema_version')!=1
            or report.get('command')!='export'
            or Path(report.get('input','')).resolve()!=cf.resolve()
            or Path(report.get('output_dir','')).resolve()!=xml.resolve()):
        raise ValueError('Partial export report belongs to another CF or directory')
    storage=report.get('export',{}).get('storage',{})
    rows=storage.get('entries')
    if storage.get('schema_version')!=1 or not isinstance(rows,list):
        raise ValueError('Partial export needs a complete storage report')
    errors=report.get('errors',[])
    if not isinstance(report.get('ok'),bool) or not isinstance(errors,list):
        raise ValueError('Invalid partial export report status')
    if any(not isinstance(row,dict) or row.get('code')!='entry_export_failed' for row in errors):
        raise ValueError('Partial export has a non-entry compiler failure')
    owners={oid:oid for oid in state['objects']}
    for oid,row in state['objects'].items():
        for name in row['externals']:
            if name in owners:raise ValueError('Ambiguous partial native stream owner')
            owners[name]=oid
    native=native_versions(cf,state)
    expected=set(owners)|repository_cache.SERVICE
    entries={};counts=dict(supported=0,opaque=0,failed=0)
    for row in rows:
        name=row.get('logical_key');status=row.get('disposition');outputs=row.get('outputs')
        if (name not in expected or name in entries or row.get('logical_name')!=name
                or row.get('part_count')!=1 or status not in counts or not isinstance(outputs,list)
                or len(outputs)!=len(set(outputs))):
            raise ValueError('Partial report inventory differs from native cache')
        outputs=[relative(path) for path in outputs]
        if MARKER in outputs:raise ValueError('Exporter output collides with workspace marker')
        entries[name]=dict(status=status,outputs=outputs,owner_id=owners.get(name),version=native.get(name),
                           reason=row.get('message',''))
        counts[status]+=1
    if (set(entries)!=expected or storage.get('logical_entries')!=len(entries)
            or storage.get('physical_entries')!=len(entries)
            or any(storage.get(k)!=v for k,v in counts.items())
            or report['ok']!=(counts['failed']==0)
            or bool(errors)!=(counts['failed']!=0)):
        raise ValueError('Partial storage report is incomplete or inconsistent')
    files=scan(xml)
    if index_file is not None:
        # Preserve the expensive completed phase for crash diagnostics before
        # inspecting metadata. This candidate is never an active baseline.
        json_file(index_file,dict(cf_sha256=state['cf_sha256'],cache_generation=state['generation'],files=files))
    if report.get('export',{}).get('files_written')!=len(files):
        raise ValueError('Partial export file count differs from report')
    if 'Configuration.xml' not in files:
        raise ValueError('Partial export needs Configuration.xml')
    root=metadata(xml/'Configuration.xml',state['root_id'],files['Configuration.xml']['sha256'])
    if root.tag!=export.Q+'Configuration':raise ValueError('Partial export has no configuration root')
    if 'ConfigDumpInfo.xml' in files:
        dump=(xml/'ConfigDumpInfo.xml').read_bytes()
        if repository_cache.digest(dump)!=files['ConfigDumpInfo.xml']['sha256']:
            raise ValueError('Partial dump info changed after hashing')
        if version_map({'ConfigDumpInfo.xml':dump})!=expected_versions(state):
            raise ValueError('Partial export versions differ from native cache')
    file_owners={name:set() for name in files}
    for name,row in entries.items():
        for path in row['outputs']:
            if path not in files:raise ValueError('Reported partial output is missing: '+path)
            if row['owner_id']:file_owners[path].add(row['owner_id'])
    def definition(item):
        oid,paths=item;definitions=[]
        for name in paths:
            node=metadata(xml/name,oid,files[name]['sha256'])
            definitions.append(dict(path=name,kind=node.tag.removeprefix(export.Q),
                                    name=node.findtext(export.Q+'Properties/'+export.Q+'Name')))
        if len(definitions)>1:raise ValueError('Ambiguous partial metadata definition: '+oid)
        return oid,definitions
    parsed={};batch=[];batch_bytes=0
    # Bound both pending jobs and the total XML input of each batch. Metadata
    # opens have high latency on Windows; never serialize 50k independent reads.
    with ThreadPoolExecutor(max_workers=IO_WORKERS) as pool:
        for oid in state['objects']:
            row=entries[oid]
            paths=[name for name in row['outputs'] if name.lower().endswith('.xml')] if row['status']=='supported' else []
            size=sum(files[name]['bytes'] for name in paths)
            if batch and (len(batch)>=512 or batch_bytes+size>64*1024*1024):
                parsed.update(pool.map(definition,batch));batch=[];batch_bytes=0
            batch.append((oid,paths));batch_bytes+=size
        parsed.update(pool.map(definition,batch))
    objects={}
    for oid,record in state['objects'].items():
        names=[oid]+sorted(record['externals']);definitions=parsed[oid]
        complete=bool(definitions) and all(entries[n]['status']=='supported' and entries[n]['outputs'] for n in names)
        objects[oid]=dict(class_id=record['class_id'],parent_id=record['parent_id'],
                          local_version=record['local'],entries=names,
                          representation='exported' if complete else 'partial' if definitions else 'unavailable',
                          definition=definitions[0] if definitions else None)
    for name,row in files.items():row['owner_ids']=sorted(file_owners[name])
    return dict(schema=1,repository_id=state['repository_id'],repository_version=state['repository_version'],
                cache_generation=state['generation'],cf_sha256=state['cf_sha256'],root_id=state['root_id'],
                counts=counts,objects=objects,entries=entries,files=files,
                compilation='addressed_standalone_modules_only',automatic_deletion=False)


def verify(folder,manifest,*,all_files=False):
    if limits.file_digest(folder/'coverage.json')!=manifest['coverage_sha256']:
        raise ValueError('Partial coverage map was modified')
    data=json.loads((folder/'coverage.json').read_text(encoding='utf-8'))
    if any(data[k]!=manifest[k] for k in ('repository_id','repository_version','cache_generation','cf_sha256','root_id')):
        raise ValueError('Partial coverage belongs to another baseline')
    marker=json.loads((folder/'xml'/MARKER).read_text(encoding='utf-8'))
    if marker!=dict(schema=1,baseline_id=manifest['baseline_id'],coverage_sha256=manifest['coverage_sha256']):
        raise ValueError('Partial baseline marker was modified')
    if all_files:
        actual=scan(folder/'xml')
        expected={name:{k:row[k] for k in ('bytes','sha256')} for name,row in data['files'].items()}
        if actual!=expected:raise ValueError('Frozen partial baseline XML was modified')
    else:
        # Ordinary reads/materialization need the verified coverage and selected
        # files, not a new 100k-file audit. Copying verifies every selected hash.
        for name in ('Configuration.xml','ConfigDumpInfo.xml'):
            if name not in data['files']:continue
            path=folder/'xml'/name
            if path.is_symlink() or limits.file_digest(path)!=data['files'][name]['sha256']:
                raise ValueError('Frozen partial baseline XML was modified')
    return data


def working_path(cache,request,key):
    path=Path(request['working_directory']).resolve() if request.get('working_directory') else cache.directory/'workspaces'/key/'xml'
    if path==cache.directory or path in cache.directory.parents:
        raise ValueError('Working XML cannot contain the repository cache')
    for protected in (cache.directory/'baselines',cache.directory/'generations'):
        if path==protected or protected in path.parents:raise ValueError('Working XML cannot be inside immutable snapshots')
    if path.exists():raise ValueError('Partial working directory must be new; existing edits are never overwritten')
    return path


def initialize(request,*,adopt=False):
    import repository_baseline as baseline
    cache=repository_cache.Cache(request['cache_directory'])
    with cache.locked():
        state,cf=cache.load_state()
        if state['generation']!=request['generation']:raise ValueError('Cache changed before partial initialization')
        identity=key(request['snapshot_id']) if adopt else uuid.uuid4().hex
        folder=cache.directory/'baselines'/identity;xml=folder/'xml'
        working=working_path(cache,request,identity)
        if (folder/'manifest.json').exists():raise ValueError('Partial snapshot has already been published')
        if adopt:
            report=json.loads(Path(request['report_file']).read_text(encoding='utf-8-sig'))
        else:
            folder.mkdir(parents=True)
            options=dict(compiler=dict(backend='ibcmd',executable=request['executable'],base_cf=str(cf)))
            with ibcmd_backend.Compiler(options) as compiler:
                try:report=compiler.execute('cf','export',cf,xml,'--platform',state['platform'])
                except ibcmd_backend.CompilationRejected as exc:
                    if exc.report is None or exc.codes!={'entry_export_failed'} or exc.report.get('ok') is not False:raise
                    report=exc.report
        data=coverage(state,cf,xml,report,index_file=folder/'file-index.json')
        # This mode intentionally never decodes/rebuilds the complete CF.
        current,current_cf=cache.load_state()
        if current!=state or current_cf!=cf:raise ValueError('Cache changed during partial export')
        json_file(folder/'export-report.json',report)
        json_file(folder/'coverage.json',data)
        checksum=limits.file_digest(folder/'coverage.json')
        marker=dict(schema=1,baseline_id=identity,coverage_sha256=checksum)
        json_file(xml/MARKER,marker)
        # Sparse by construction: absence of every other file means "not
        # materialized", never "delete". Copies share no writable inodes.
        working.mkdir(parents=True)
        selected={name:data['files'][name] for name in ('Configuration.xml','ConfigDumpInfo.xml') if name in data['files']}
        copy_files(xml,working,selected)
        json_file(working/MARKER,marker)
        manifest=dict(schema=1,kind='partial',baseline_id=identity,repository_id=state['repository_id'],
                      root_id=state['root_id'],platform=state['platform'],repository_version=state['repository_version'],
                      cache_generation=state['generation'],cf_sha256=state['cf_sha256'],coverage_sha256=checksum,
                      coverage_file=str(folder/'coverage.json'),working_directory=str(working),working_directory_created=True,
                      workspace_layout='sparse',automatic_deletion=False,compilation=data['compilation'],
                      file_count=len(data['files']),object_count=len(data['objects']),export_counts=data['counts'])
        return baseline.publish(cache,folder,manifest)


def copy_files(source,target,files):
    for name,row in files.items():
        relative(name);path=target/name
        if path.exists() or path.is_symlink():raise ValueError('Refusing to overwrite a materialized file: '+name)
        path.parent.mkdir(parents=True,exist_ok=True)
        if target.resolve() not in path.resolve().parents:raise ValueError('Working path escapes workspace')
        if limits.file_digest(source/name)!=row['sha256']:raise ValueError('Frozen source file was modified: '+name)
        with (source/name).open('rb') as incoming,path.open('xb') as outgoing:
            shutil.copyfileobj(incoming,outgoing,1024*1024)
        if limits.file_digest(path)!=row['sha256']:raise ValueError('Materialized file checksum mismatch')


def materialize(request):
    """Copy selected owners for editing. No CF compiler and no repository I/O."""
    import repository_baseline as baseline
    cache=repository_cache.Cache(request['cache_directory'])
    with cache.locked():
        basis=baseline.read(cache.directory)
        if basis.get('kind')!='partial':raise ValueError('Materialization requires a partial baseline')
        if basis['baseline_id']!=request['baseline_id']:raise ValueError('Active partial baseline changed')
        folder=Path(basis['manifest_file']).parent
        data=json.loads((folder/'coverage.json').read_text(encoding='utf-8'))
        wanted=request.get('object_ids')
        if not isinstance(wanted,list) or not wanted or any(oid not in data['objects'] for oid in wanted):
            raise ValueError('Select existing partial baseline object_ids')
        target=Path(basis['working_directory']);marker=target/MARKER
        if target.is_symlink() or target.resolve()!=target or marker.is_symlink() or marker.read_bytes()!=(folder/'xml'/MARKER).read_bytes():
            raise ValueError('Working directory belongs to another partial baseline')
        selected={name:row for name,row in data['files'].items() if set(row['owner_ids']) & set(wanted)}
        for name,row in selected.items():
            source=folder/'xml'/name
            if source.is_symlink() or (folder/'xml').resolve() not in source.resolve().parents or limits.file_digest(source)!=row['sha256']:
                raise ValueError('Frozen source file was modified: '+name)
        # Check *all* destination paths before creating anything. Changed or
        # symlinked files are never overwritten, including on a retry.
        pending={}
        for name,row in selected.items():
            path=target/name
            if path.is_symlink() or target.resolve() not in path.resolve().parents:
                raise ValueError('Working path escapes workspace')
            if path.exists():
                if limits.file_digest(path)!=row['sha256']:raise ValueError('Working file has local changes: '+name)
            else:pending[name]=row
        copy_files(folder/'xml',target,pending)
        return dict(baseline_id=basis['baseline_id'],working_directory=str(target),copied_files=sorted(pending),
                    objects={oid:data['objects'][oid] for oid in wanted},captured=False,committed=False)
