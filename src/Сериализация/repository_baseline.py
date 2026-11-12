"""Explicit immutable repository baselines, independent of Git."""
import base64
import copy
import json
import os
from pathlib import Path
import uuid

import configuration_export as export
from export_snapshot import version_map,expected_versions,write_files
import ibcmd_backend
import native_metadata as s
import repository_cache
import resource_limits as limits


def publish(cache,folder,manifest):
    raw=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    (folder/'manifest.json').write_bytes(raw)
    pointer=dict(baseline_id=manifest['baseline_id'],manifest_sha256=repository_cache.digest(raw))
    temporary=cache.directory/('baseline-'+manifest['baseline_id']+'.tmp')
    temporary.write_text(json.dumps(pointer),encoding='utf-8')
    os.replace(str(temporary),str(cache.directory/'baseline.json'))
    return dict(manifest,baseline_directory=str(folder/'xml'),base_cf=str(cache.directory/'generations'/manifest['cache_generation']/'base.cf'),manifest_file=str(folder/'manifest.json'))


def object_versions(objects):
    return {oid:{key:row[key] for key in ('class_id','parent_id','local','externals')} for oid,row in objects.items()}


def compiled_version(atom):
    raw=base64.b64decode(s.val(atom),validate=True)
    if len(raw)!=20:raise ValueError('Invalid compiled version')
    return str(uuid.UUID(bytes_le=raw[:16]))


def register(request,changed,payload,removed=()):
    """Save exactly the compiled input and expected server contents before sending."""
    cache=repository_cache.Cache(request['baseline_update']['cache_directory'])
    with cache.locked():
        basis=read(cache.directory)
        if basis.get('kind')=='partial':raise ValueError('Whole-configuration receipts are unavailable for partial XML baselines')
        state,image,_=cache.load()
        settings=request['baseline_update']
        if not isinstance(settings.get('use_git',False),bool):raise ValueError('use_git must be boolean')
        git=None
        if settings.get('use_git'):
            from xml_git import Git,DEFAULT_SOURCE_BRANCH
            git=Git(settings.get('xml_repository',cache.directory/'xml.git'),settings.get('source_branch',DEFAULT_SOURCE_BRANCH))
        if basis['baseline_id']!=settings['baseline_id'] or state['generation']!=settings['generation']:
            raise ValueError('Baseline or cache changed during packet preparation')
        if state['repository_version']!=request['repository_version']:raise ValueError('Receipt source version differs from cache')
        _,files,inventory,root=export.inventory(request['directory'])
        if export.fingerprint(files)!=request['target_fingerprint'] or root['id']!=state['root_id']:raise ValueError('XML changed before saving commit receipt')
        objects=copy.deepcopy(state['objects'])
        for oid in removed:objects.pop(oid)
        for oid,(docs,body,streams) in changed.items():
            if oid not in objects:
                objects[oid]=dict(original=compiled_version(docs[0][7]),class_id=s.val(docs[0][2]),parent_id=s.val(docs[0][3]))
            m=docs[0];objects[oid]['local']=compiled_version(m[8])
            refs=m[11];objects[oid]['externals']={s.val(refs[i]):compiled_version(refs[i+1]) for i in range(1,len(refs),2)}
            image[oid]=body
            for name,packed in streams:image[name]=s.inflate(packed)
        wanted=set(objects)|{name for row in objects.values() for name in row['externals']}
        if set(inventory)!=set(objects):raise ValueError('Submitted XML inventory differs from expected repository objects')
        entries={name:repository_cache.digest(image[name]) for name in wanted}
        key=uuid.uuid4().hex;folder=cache.directory/'pending'/key;folder.mkdir(parents=True)
        write_files(folder/'xml',files,exclusive=True)
        receipt=dict(schema=1,receipt_id=key,baseline_id=basis['baseline_id'],repository_id=state['repository_id'],
                     root_id=state['root_id'],platform=state['platform'],source_version=state['repository_version'],
                     working_directory=str(Path(request['directory']).resolve()),xml_fingerprint=export.fingerprint(files),
                     packet_sha256=repository_cache.digest(payload),expected_entries=entries,expected_objects=object_versions(objects))
        if git is not None:
            receipt.update(git_directory=str(git.directory),source_branch=git.source_branch)
        raw=(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode('utf-8');(folder/'receipt.json').write_bytes(raw)
        return dict(cache_directory=str(cache.directory),receipt_id=key,receipt_sha256=repository_cache.digest(raw),executable=request['compiler']['executable'])


def advance(request):
    """Promote the submitted XML only when the received native version matches it."""
    cache=repository_cache.Cache(request['cache_directory'])
    with cache.locked():
        key=request['receipt_id']
        if not isinstance(key,str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):raise ValueError('Invalid receipt identity')
        pending=cache.directory/'pending'/key;raw=(pending/'receipt.json').read_bytes()
        if repository_cache.digest(raw)!=request['receipt_sha256']:raise ValueError('Commit receipt checksum mismatch')
        receipt=json.loads(raw)
        if receipt['schema']!=1 or receipt['receipt_id']!=key:raise ValueError('Invalid commit receipt')
        if repository_cache.digest(base64.b64decode(request['packet'],validate=True))!=receipt['packet_sha256']:raise ValueError('Packet differs from commit receipt')
        basis=read(cache.directory)
        if basis.get('receipt_id')==key:return dict(basis,updated=True,committed=True)
        if basis['baseline_id']!=receipt['baseline_id']:raise ValueError('Active baseline changed; refusing to replace it')
        state,image,cf=cache.load()
        if request['generation']!=state['generation']:raise ValueError('Cache changed before baseline promotion')
        if any(state[k]!=receipt[k] for k in ('repository_id','root_id','platform')):raise ValueError('Receipt belongs to another repository')
        if state['repository_version']==receipt['source_version']:raise ValueError('Repository has not confirmed a new version')
        entries={name:repository_cache.digest(raw) for name,raw in image.items() if name not in repository_cache.SERVICE}
        if entries!=receipt['expected_entries'] or object_versions(state['objects'])!=receipt['expected_objects']:
            raise ValueError('Received repository contents differ from the submitted packet; baseline retained')
        _,files,_,_=export.inventory(pending/'xml')
        if export.fingerprint(files)!=receipt['xml_fingerprint']:raise ValueError('Submitted XML snapshot was modified')
        new=uuid.uuid4().hex;folder=cache.directory/'baselines'/new;folder.mkdir(parents=True)
        with ibcmd_backend.Compiler(dict(compiler=dict(backend='ibcmd',executable=request['executable'],base_cf=str(cf)))) as compiler:
            compiler.execute('cf','export',cf,folder/'received','--platform',state['platform'])
        _,received,received_records,root=export.inventory(folder/'received')
        ibcmd_backend.require_complete_export(image,received_records,received)
        if root['id']!=state['root_id'] or version_map(received)!=expected_versions(state):raise ValueError('Received XML versions differ from cache')
        # Keep the submitted representation, including stable form helper IDs.
        # Never overwrite working files: they may contain edits made after prepare.
        files=dict(files);files['ConfigDumpInfo.xml']=received['ConfigDumpInfo.xml']
        write_files(folder/'xml',files,exclusive=True)
        manifest=dict(schema=1,baseline_id=new,repository_id=state['repository_id'],root_id=state['root_id'],platform=state['platform'],
                      repository_version=state['repository_version'],cache_generation=state['generation'],cf_sha256=limits.file_digest(cf),
                      xml_fingerprint=export.fingerprint(files),working_directory=receipt['working_directory'],working_directory_created=False,receipt_id=key)
        if receipt.get('git_directory'):
            from xml_git import Git,record_source,retain_unchanged,DEFAULT_SOURCE_BRANCH
            git=Git(receipt['git_directory'],receipt.get('source_branch',DEFAULT_SOURCE_BRANCH));git.initialize();head,_=git.history(state)
            if head:
                write_files(folder/'previous',git.files(head))
                received=retain_unchanged(folder/'previous',folder/'received')
            commit=record_source(git,state,received)
            manifest.update(git_directory=str(git.directory),repository_commit=commit,source_branch=git.source_branch)
        return dict(publish(cache,folder,manifest),updated=True,committed=True)


def read(directory,*,verify_all_files=False):
    cache=repository_cache.Cache(directory)
    if not (cache.directory/'baseline.json').is_file():raise ValueError('Initialize the XML baseline first')
    pointer=json.loads((cache.directory/'baseline.json').read_text(encoding='utf-8'))
    key=pointer['baseline_id']
    if not isinstance(key,str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):raise ValueError('Invalid baseline identity')
    folder=cache.directory/'baselines'/key;raw=(folder/'manifest.json').read_bytes()
    if repository_cache.digest(raw)!=pointer['manifest_sha256']:raise ValueError('Baseline manifest checksum mismatch')
    manifest=json.loads(raw)
    if manifest['schema']!=1 or manifest['baseline_id']!=key:raise ValueError('Invalid baseline manifest')
    if manifest.get('kind')=='partial':
        import partial_baseline
        partial_baseline.verify(folder,manifest,all_files=verify_all_files)
    else:
        files=export.inventory(folder/'xml')[1]
        if export.fingerprint(files)!=manifest['xml_fingerprint']:raise ValueError('Frozen baseline XML was modified')
    generation=manifest['cache_generation']
    if not isinstance(generation,str) or len(generation)!=32 or any(c not in '0123456789abcdef' for c in generation):raise ValueError('Invalid baseline CF generation')
    cf=cache.directory/'generations'/generation/'base.cf'
    if limits.file_digest(cf)!=manifest['cf_sha256']:raise ValueError('Frozen baseline CF was modified')
    return dict(manifest,baseline_directory=str(folder/'xml'),base_cf=str(cf),manifest_file=str(folder/'manifest.json'))


def initialize(request):
    if not isinstance(request.get('allow_partial',False),bool):raise ValueError('allow_partial must be boolean')
    if request.get('allow_partial'):
        import partial_baseline
        return partial_baseline.initialize(request)
    cache=repository_cache.Cache(request['cache_directory'])
    with cache.locked():
        state,cf=cache.load_state()
        if request['generation']!=state['generation']:raise ValueError('Cache changed before baseline initialization')
        key=uuid.uuid4().hex
        folder=cache.directory/'baselines'/key
        working=Path(request['working_directory']).resolve() if request.get('working_directory') else cache.directory/'workspaces'/key/'xml'
        if working==cache.directory or working in cache.directory.parents:raise ValueError('Working XML cannot contain the repository cache')
        for protected in (cache.directory/'baselines',cache.directory/'generations'):
            if working==protected or protected in working.parents:raise ValueError('Working XML cannot be inside immutable snapshots')
        original=None
        if working.exists():
            _,original,_,root=export.inventory(working)
            if root['id']!=state['root_id'] or version_map(original)!=expected_versions(state):
                raise ValueError('Existing XML has a different base version; initialize before edits or supply a known historical baseline')
        folder.mkdir(parents=True)
        xml=folder/'xml'
        options=dict(compiler=dict(backend='ibcmd',executable=request['executable'],base_cf=str(cf)))
        with ibcmd_backend.Compiler(options) as compiler:
            compiler.execute('cf','export',cf,xml,'--platform',state['platform'])
        # Avoid retaining the complete decoded CF alongside the compiler's own
        # image. All native/image checks still run before publishing the basis.
        verified,image,verified_cf=cache.load()
        if verified!=state or verified_cf!=cf:raise ValueError('Cache changed during baseline export')
        _,files,records,root=export.inventory(xml)
        ibcmd_backend.require_complete_export(image,records,files)
        if root['id']!=state['root_id'] or version_map(files)!=expected_versions(state):raise ValueError('Baseline export differs from repository versions')
        created=original is None
        if created:
            working.parent.mkdir(parents=True,exist_ok=True)
            working.mkdir()
            write_files(working,files,exclusive=True)
        elif export.fingerprint(export.inventory(working)[1])!=export.fingerprint(original):
            raise ValueError('Working XML changed during baseline initialization')
        manifest=dict(schema=1,baseline_id=key,repository_id=state['repository_id'],root_id=state['root_id'],
                      platform=state['platform'],repository_version=state['repository_version'],cache_generation=state['generation'],
                      cf_sha256=limits.file_digest(cf),xml_fingerprint=export.fingerprint(files),
                      working_directory=str(working),working_directory_created=created)
        return publish(cache,folder,manifest)


def run(request):
    if request['mode']=='adopt_partial':
        import partial_baseline
        return partial_baseline.initialize(request,adopt=True)
    if request['mode']=='materialize':
        import partial_baseline
        return partial_baseline.materialize(request)
    if request['mode']=='initialize':return initialize(request)
    if request['mode']=='read':
        if not isinstance(request.get('verify_all_files',False),bool):raise ValueError('verify_all_files must be boolean')
        result=read(request['cache_directory'],verify_all_files=request.get('verify_all_files',False))
        if request.get('working_directory') and Path(request['working_directory']).resolve()!=Path(result['working_directory']).resolve():
            raise ValueError('Use the active baseline working_directory or supply an explicit XML baseline')
        return result
    if request['mode']=='advance':return advance(request)
    raise ValueError('Unknown baseline mode')


if __name__=='__main__':
    from serializer_cli import run as cli
    cli(run)
