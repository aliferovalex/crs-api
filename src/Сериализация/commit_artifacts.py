"""Reviewed, one-attempt agent commits. Transport stays in the OneScript API."""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

import external_data
import native_metadata as native
from native_storage_file import FileStorage
import preparation_journal as journal
import repository_cache
import resource_limits as limits

MAX_JSON=128*1024*1024


class CommitError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def fail(message,code='commit_conflict'):raise CommitError(code,message)
def digest(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return journal.encoded(value)


def read_raw(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_JSON:fail('Missing/oversized commit JSON')
    with path.open('rb') as stream:raw=stream.read(MAX_JSON+1)
    if len(raw)>MAX_JSON:fail('Oversized commit JSON')
    return raw


def load(path):return decode(read_raw(path))


def decode(raw):
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result:fail('Duplicate commit JSON key')
            result[k]=v
        return result
    return json.loads(raw.decode('utf-8-sig'),object_pairs_hook=unique,
                      parse_constant=lambda _:fail('Non-finite commit JSON'))


def seal(path,data):
    journal.atomic(Path(path),dict(schema=1,data=data,sha256=digest(encoded(data))))
    return limits.file_digest(path)


def unseal(path,expected=None):
    raw=read_raw(path)
    if expected is not None and digest(raw)!=expected:fail('Approved commit file changed')
    envelope=decode(raw)
    if envelope.get('schema')!=1 or envelope.get('sha256')!=digest(encoded(envelope['data'])):fail('Commit metadata checksum mismatch')
    return envelope['data']


def checksum(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):fail('Expected lowercase SHA256')
    return value


def artifact(directory,expected=None):
    directory=Path(directory).resolve();path=directory/'prepared.json'
    data=unseal(path,expected)
    packet=directory/'packet.bin'
    if packet.is_symlink() or directory not in packet.resolve().parents:fail('Packet path escapes prepared directory')
    if (not packet.is_file() or not 0<packet.stat().st_size<=limits.get('packet_bytes')
            or limits.file_digest(packet)!=data['packet_sha256']):fail('Prepared packet changed')
    validate(data)
    return data


def validate(data):
    if data.get('schema')!=1:fail('Unknown prepared artifact schema')
    binding=data['binding'];uuid.UUID(binding['repository_id']);uuid.UUID(data['packet']['repository_version'])
    dto=data['packet'];sources=data['sources']
    def ids(rows):
        values=[str(uuid.UUID(row['id'])) for row in rows]
        if len(values)!=len(set(values)):fail('Duplicate prepared object')
        return values
    source_ids=ids(sources);changed=dto['changed_ids'];created=dto['new_ids'];removed=dto['removed_ids']
    for values in (changed,created,removed):
        if not isinstance(values,list) or ids([dict(id=value) for value in values])!=values:fail('Invalid prepared object IDs')
    if not sources or not changed:fail('A commit requires existing changed parent/object sources')
    if ids(dto['descriptions'])!=changed+created or set(source_ids)!=set(changed)|set(removed):fail('Prepared object scope mismatch')
    if set(changed)&set(created) or set(removed)&(set(changed)|set(created)):fail('Overlapping prepared operations')
    if set(ids(dto['verification']))!=set(changed)|set(created):fail('Prepared readback coverage mismatch')
    for row in sources:
        for k in ('original','local'):
            if not re.fullmatch('[0-9a-f]{40}',row[k]):fail('Invalid source object version')
        if type(row['version']) is not int or type(row['own_version']) is not int:fail('Invalid source version number')
    for row in dto['verification']:
        checksum(row['body_sha256'])
        names=[stream['name'] for stream in row['streams']]
        if len(names)!=len(set(names)):fail('Duplicate readback stream')
        for stream in row['streams']:checksum(stream['sha256'])
    checksum(data['packet_sha256'])
    if dto['repository']!=binding['repository'] or dto['platform']!=binding['platform']:fail('Prepared repository binding mismatch')


def save(request):
    directory=Path(request['directory']).resolve();packet=directory/'packet.bin'
    data=dict(schema=1,binding=request['binding'],sources=request['sources'],packet=request['packet'],packet_sha256=limits.file_digest(packet))
    if request.get('baseline_update') is not None:data['baseline_update']=request['baseline_update']
    validate(data)
    path=directory/'prepared.json'
    if path.exists():fail('Prepared artifact already exists')
    value=seal(path,data)
    return dict(prepared_file=str(path),prepared_sha256=value)


def compatible(binding,config):
    if binding['url']!=config['url'] or binding['platform']!=config['platform']:fail('Prepared packet belongs to another repository/profile')
    if config.get('repository') is not None and config['repository']!=binding['repository']:fail('Prepared alias differs from profile')


def make_plan(params,config,runner):
    directory=Path(params['prepared_directory'])
    review=directory/'review.json'
    review_raw=read_raw(review);reviewed=decode(review_raw);review_hash=digest(review_raw)
    if reviewed.get('has_changes') is not True:fail('Preparation has no changes','no_changes')
    artifact_hash=limits.file_digest(directory/'prepared.json')
    data=artifact(directory,artifact_hash);compatible(data['binding'],config)
    probe=runner('commit.inspect',dict(prepared_directory=str(directory),prepared_sha256=artifact_hash))
    if probe['repository_id']!=data['binding']['repository_id']:fail('Repository identity changed')
    label=params.get('label');comment=params['comment']
    task=re.match(r'^#?([A-Z][A-Z0-9]*-\d+):',comment)
    if task:
        if not comment.startswith('#'):fail('Jira commit comment must start with #KEY:')
        wanted='#'+task.group(1)
        if label is None:label=wanted
        if label!=wanted:fail('Jira label must equal the comment task key with #')
    key=uuid.uuid4().hex;folder=Path(config['state_directory'])/'plans'/key;folder.mkdir(parents=True)
    operation=Path(config['state_directory'])/'operations'/(data['binding']['repository_id'].replace('-','')+'-'+data['packet_sha256'])
    plan=dict(schema=1,plan_id=key,prepared_directory=str(directory),prepared_sha256=artifact_hash,
              review_file=str(review),review_sha256=review_hash,packet_sha256=data['packet_sha256'],
              target=dict(data['binding'],username=config['username'],user_id=probe['user_id']),
              source_repository_version=data['packet']['repository_version'],comment=comment,
              label=dict(name=label,status='not_supported' if label else 'not_requested'),
              configuration_version=probe['configuration_version'],capture_ids=[r['id'] for r in data['sources']],
              changes=data['packet']['descriptions'],removed_ids=data['packet']['removed_ids'],
              sources=data['sources'],captures=probe['captures'],ready=probe['ready'],conflicts=probe['conflicts'],
              operation_directory=str(operation),automatic_retry=False)
    plan_file=folder/'plan.json';sha=seal(plan_file,plan)
    # The native packet and its review must remain the exact prepared input.
    artifact(directory,artifact_hash)
    if limits.file_digest(review)!=review_hash:fail('Review changed during planning')
    return dict(plan=plan,review=reviewed,plan_file=str(plan_file),plan_sha256=sha,executed=False,captured=False,committed=False)


def read_plan(params,config,verify_inputs=True):
    plan=unseal(params['plan_file'],params.get('approved_plan_sha256') or params.get('plan_sha256'))
    if plan['schema']!=1:fail('Unknown commit plan schema')
    compatible(plan['target'],config)
    if plan['target']['username']!=config['username']:fail('Approved commit user differs from profile')
    expected=Path(config['state_directory'])/'operations'/(plan['target']['repository_id'].replace('-','')+'-'+plan['packet_sha256'])
    if Path(plan['operation_directory']).resolve()!=expected.resolve():fail('Commit operation registry differs from plan')
    if verify_inputs:
        data=artifact(plan['prepared_directory'],plan['prepared_sha256'])
        if data['packet_sha256']!=plan['packet_sha256'] or limits.file_digest(plan['review_file'])!=plan['review_sha256']:fail('Approved prepared input changed')
    return plan


def checked_result(result,already_executed=False):
    result=dict(result,already_executed=already_executed)
    if result.get('outcome_unknown'):fail('Commit outcome is unknown; use changes.status, never resend','outcome_unknown')
    if result.get('committed') is not True:fail('Commit was not confirmed; use changes.status for the recorded phase','commit_failed')
    return result


def execute(params,config,runner):
    if params.get('execute') is not True:fail('Explicit execute=true is required','approval_required')
    plan=read_plan(params,config)
    if not plan['ready']:fail('Commit plan has unresolved conflicts')
    operation=Path(plan['operation_directory']);operation.mkdir(parents=True,exist_ok=True)
    with journal.locked(operation):
        attempted=operation/'attempt.json';result_file=operation/'result.json'
        if attempted.exists():
            old=unseal(attempted)
            if old['plan_sha256']!=params['approved_plan_sha256']:fail('This packet already has a commit attempt; inspect its status','operation_already_attempted')
            if result_file.exists():return checked_result(unseal(result_file),already_executed=True)
            fail('Commit attempt already started; inspect status, never resend automatically','outcome_unknown')
        seal(attempted,dict(plan_file=str(Path(params['plan_file']).resolve()),plan_sha256=params['approved_plan_sha256'],
                            repository_id=plan['target']['repository_id'],packet_sha256=plan['packet_sha256']))
        # A crash from this point is an inspect-only operation, including lost
        # capture replies. The journal is written by the existing lifecycle.
        result=runner('commit.execute',dict(plan_file=str(params['plan_file']),plan_sha256=params['approved_plan_sha256']))
        seal(result_file,result)
        return checked_result(result)


def status(params,config,runner):
    plan=read_plan(params,config,verify_inputs=False);operation=Path(plan['operation_directory'])
    out=dict(operation_directory=str(operation),attempted=(operation/'attempt.json').exists(),automatic_retry=False)
    for name,key in (('journal.json','journal'),('result.json','result')):
        if (operation/name).exists():out[key]=unseal(operation/name)
    try:
        read_plan(params,config)
        out['observed']=runner('commit.inspect',dict(prepared_directory=plan['prepared_directory'],prepared_sha256=plan['prepared_sha256'],strict_source=False))
    except (ValueError,OSError):
        out['observation_error']='Cannot inspect current objects with the approved inputs; the local journal is still available'
    return out


def journal_action(request):
    directory=Path(request['directory']).resolve();attempt=unseal(directory/'attempt.json')
    owner=journal.process_identity(os.getppid())
    if owner is None:fail('Cannot identify commit process')
    path=directory/'journal.json'
    with journal.locked(directory/'journal-lock'):
        if request['mode']=='journal_create':
            if path.exists() or request['plan_sha256']!=attempt['plan_sha256']:fail('Commit journal already exists or approval changed')
            data=dict(schema=1,revision=0,owner=owner,snapshot=request['snapshot'])
        else:
            data=unseal(path)
            if data['owner']!=owner or data['revision']!=request['revision']:fail('Commit journal changed or has another owner')
            data.update(revision=data['revision']+1,snapshot=request['snapshot'])
        journal.validate(data['snapshot']);seal(path,data)
    return dict(directory=str(directory),revision=data['revision'],snapshot=data['snapshot'])


def verify_snapshot(request):
    plan=unseal(request['plan_file'],request['plan_sha256'])
    data=artifact(plan['prepared_directory'],plan['prepared_sha256']);oid=request['object_id']
    proof=next(row for row in data['packet']['verification'] if row['id']==oid)
    wanted=dict(body_sha256=proof['body_sha256'],streams={row['name']:row['sha256'] for row in proof['streams']})
    source=FileStorage(request['snapshot_file'])
    for _,docs,body,streams in external_data.iter_native(source,{oid}):
        actual=dict(body_sha256=digest(native.inflate(body)),streams={name:digest(native.inflate(value)) for name,value in streams.items()})
        if actual!=wanted:fail('Committed native contents differ from the reviewed packet','readback_mismatch')
    return dict(verified=True,object_id=oid)


def run(request):
    mode=request['mode']
    if mode=='identity':return dict(repository_id=repository_cache.identity(dict(repository_info=request['repository_info'])))
    if mode=='save':return save(request)
    if mode in ('journal_create','journal_save'):
        (Path(request['directory'])/'journal-lock').mkdir(exist_ok=True)
        return journal_action(request)
    if mode=='verify_snapshot':return verify_snapshot(request)
    fail('Unknown commit artifact mode')


if __name__=='__main__':
    from serializer_cli import run as cli
    cli(run)
