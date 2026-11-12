"""JSON boundary for agents; transport and compilation belong to CRS API."""
import argparse
import base64
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
SERIALIZATION = ROOT / 'src' / 'Сериализация'
ACTIONS = {
    'connect': set(),
    'objects.search': {'query', 'kind', 'class_id', 'offset', 'limit'},
    'objects.read': {'object_id', 'format'},
    'workspace.init': {'directory', 'allow_partial'},
    'workspace.materialize': {'baseline_id', 'object_ids'},
    'changes.prepare': {'directory', 'baseline_directory', 'output_directory'},
    'modules.prepare': {'object_id', 'module_path', 'source_file', 'expected_source_sha256', 'output_directory'},
    'changes.plan': {'prepared_directory','comment','label'},
    'changes.commit': {'plan_file','approved_plan_sha256','execute'},
    'changes.status': {'plan_file','plan_sha256'},
    'users.list': set(),
    'users.plan': {'operation', 'user_id', 'name', 'role', 'password_env'},
    'users.apply': {'operation', 'user_id', 'name', 'role', 'password_env', 'execute', 'expected'},
}
ROLES = {'read_only': '0', 'developer': '1', 'developer_extended': '5', 'admin': '32773'}


class CLIError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def fail(message, code='invalid_request'):
    raise CLIError(code, message)


def load_json(raw, limit=8 * 1024 * 1024):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: fail('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    if len(raw) > limit: fail('JSON exceeds size limit')
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique,
                          parse_constant=lambda value: fail('Non-finite JSON value'))
    except (UnicodeError, json.JSONDecodeError):
        fail('Expected UTF-8 JSON')


def keys(value, allowed, label):
    if not isinstance(value, dict): fail(label + ' must be an object')
    if set(value) - set(allowed): fail('Unknown ' + label + ' fields: ' + ', '.join(sorted(set(value)-set(allowed))))


def string(value, label, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or '\0' in value:
        fail(label + ' must be a string' + ('' if empty else ' and not empty'))
    return value


def guid(value, label):
    try: result = str(uuid.UUID(string(value, label)))
    except (ValueError, AttributeError): fail(label + ' must be a UUID')
    if result == str(uuid.UUID(int=0)): fail(label + ' must not be zero')
    return result


def validate(request):
    keys(request, {'schema', 'action', 'profile', 'params'}, 'request')
    if type(request.get('schema')) is not int or request['schema'] != 1: fail('schema must be 1')
    action = string(request.get('action'), 'action')
    if action not in ACTIONS: fail('Unknown action')
    string(request.get('profile'), 'profile')
    params = request.setdefault('params', {})
    keys(params, ACTIONS[action], 'params')
    if action == 'objects.search':
        params.setdefault('query', ''); string(params['query'], 'query', True)
        for name, default, low, high in [('offset', 0, 0, 10000000), ('limit', 100, 1, 1000)]:
            value = params.setdefault(name, default)
            if type(value) is not int or not low <= value <= high: fail(name + ' is out of range')
        if 'kind' in params:
            sys.path.insert(0, str(SERIALIZATION))
            import metadata_identifiers
            names = {v: k for k, v in metadata_identifiers.class_labels().items()}
            if params['kind'] not in names: fail('Unknown metadata kind')
            resolved = names[params.pop('kind')]
            if 'class_id' in params and guid(params['class_id'], 'class_id') != resolved: fail('kind and class_id disagree')
            params['class_id'] = resolved
        if 'class_id' in params: params['class_id'] = guid(params['class_id'], 'class_id')
    if action == 'objects.read':
        params['object_id'] = guid(params.get('object_id'), 'object_id')
        if params.setdefault('format', 'xml') not in ('native', 'xml'): fail('format must be native or xml')
    if action == 'modules.prepare':
        params['object_id'] = guid(params.get('object_id'), 'object_id')
        string(params.get('module_path'), 'module_path')
        if not isinstance(params.get('expected_source_sha256'), str) or not re.fullmatch('[0-9a-f]{64}', params['expected_source_sha256']): fail('expected_source_sha256 must be a lowercase SHA256')
        source = Path(string(params.get('source_file'), 'source_file')).resolve()
        if not source.is_file(): fail('source_file must exist')
        params['source_file'] = str(source)
        out = Path(string(params.get('output_directory'), 'output_directory')).resolve()
        if out.exists() or out == source or out in source.parents: fail('output_directory must be a new separate directory')
        params['output_directory'] = str(out)
    if action=='changes.plan':
        path=Path(string(params.get('prepared_directory'),'prepared_directory')).resolve()
        if not path.is_dir():fail('prepared_directory must exist')
        params['prepared_directory']=str(path)
        if len(string(params.get('comment'),'comment'))>65536:fail('Comment is oversized')
        if 'label' in params and len(string(params['label'],'label'))>256:fail('Label is oversized')
    if action in ('changes.commit','changes.status'):
        params['plan_file']=str(Path(string(params.get('plan_file'),'plan_file')).resolve())
        name='approved_plan_sha256' if action=='changes.commit' else 'plan_sha256'
        if not isinstance(params.get(name),str) or not re.fullmatch('[0-9a-f]{64}',params[name]):fail(name+' must be lowercase SHA256')
        if action=='changes.commit' and params.get('execute') is not True:fail('changes.commit requires execute=true after explicit approval')
    if action in ('workspace.init', 'changes.prepare'):
        params['directory'] = str(Path(string(params.get('directory'), 'directory')).resolve())
    if action == 'workspace.init' and 'allow_partial' in params:
        if type(params['allow_partial']) is not bool: fail('allow_partial must be boolean')
    if action == 'workspace.materialize':
        if not isinstance(params.get('baseline_id'),str) or not re.fullmatch('[0-9a-f]{32}',params['baseline_id']): fail('baseline_id must be 32 lowercase hex characters')
        ids=params.get('object_ids')
        if not isinstance(ids,list) or not 1<=len(ids)<=1000: fail('object_ids must contain 1..1000 UUIDs')
        params['object_ids']=[guid(value,'object_ids') for value in ids]
        if len(set(params['object_ids']))!=len(ids): fail('Duplicate object_ids')
    if action == 'changes.prepare':
        params['output_directory'] = str(Path(string(params.get('output_directory'), 'output_directory')).resolve())
        if 'baseline_directory' in params: params['baseline_directory'] = str(Path(string(params['baseline_directory'], 'baseline_directory')).resolve())
        for name in ('directory', 'baseline_directory'):
            if name in params and not Path(params[name]).is_dir(): fail(name + ' must exist')
        out = Path(params['output_directory'])
        for name in ('directory', 'baseline_directory'):
            if name in params:
                source = Path(params[name])
                if out == source or out in source.parents or source in out.parents: fail('output_directory must be separate from XML sources')
        if out.exists(): fail('output_directory must not exist')
    if action.startswith('users.') and action != 'users.list':
        operation = params.get('operation')
        if operation not in ('create', 'update', 'delete', 'restore'): fail('Unknown user operation')
        if operation == 'create':
            string(params.get('name'), 'name')
            if 'user_id' in params: fail('create does not accept user_id')
        else: params['user_id'] = guid(params.get('user_id'), 'user_id')
        if 'name' in params: string(params['name'], 'name')
        if operation in ('delete', 'restore') and set(params) & {'name', 'role', 'password_env'}: fail('delete/restore only accept user_id and expected')
        if operation == 'create': params.setdefault('role', 'read_only')
        if 'role' in params and string(params['role'],'role') not in ROLES: fail('Unknown user role')
        if operation == 'create' or 'password_env' in params: string(params.get('password_env'), 'password_env')
        if operation == 'update' and not set(params) & {'name', 'role', 'password_env'}: fail('Empty user update')
        if action == 'users.apply':
            if params.get('execute') is not True: fail('users.apply requires execute=true after approval')
            if operation != 'create':
                expected = params.get('expected')
                keys(expected, {'id', 'name', 'role', 'rights', 'deleted'}, 'expected')
                if set(expected) != {'id', 'name', 'role', 'rights', 'deleted'}: fail('expected must contain id, name, role, rights, deleted')
                if guid(expected['id'], 'expected.id') != params['user_id']: fail('expected.id disagrees with user_id')
                string(expected['name'], 'expected.name', True)
                if string(expected['role'],'expected.role') not in (*ROLES,'unknown') or type(expected['deleted']) is not bool: fail('Invalid expected user state')
                rights=string(expected['rights'],'expected.rights')
                if not rights.isascii() or not rights.isdecimal() or int(rights)>2**32-1: fail('Invalid expected rights')
            if 'password_env' in params and params['password_env'] not in os.environ: fail('New password environment variable is not set', 'configuration_error')
    return request


def configuration(path, profile, action, params):
    local_only=action=='workspace.materialize'
    path = Path(path).resolve()
    try: config = load_json(path.read_bytes())
    except OSError: fail('Cannot read config file', 'configuration_error')
    keys(config, {'schema', 'repositories', 'runtime'}, 'config')
    if type(config.get('schema')) is not int or config['schema'] != 1 or not isinstance(config.get('repositories'), dict): fail('Invalid config', 'configuration_error')
    selected = config['repositories'].get(profile)
    keys(selected, {'url', 'platform', 'username', 'password_env', 'repository', 'cache_directory', 'limits', 'operation_timeout_seconds', 'compiler_timeout_seconds'}, 'repository')
    for name,default in [('operation_timeout_seconds',600),('compiler_timeout_seconds',240)]:
        timeout=selected.get(name,default)
        if type(timeout) is not int or not 1<=timeout<=86400:fail(name+' must be an integer from 1 to 86400','configuration_error')
    sys.path.insert(0,str(SERIALIZATION))
    import resource_limits
    try: policy = {**resource_limits.overrides(), **resource_limits.validate(selected.get('limits', {}))}
    except (ValueError, OSError): fail('Invalid resource limits', 'configuration_error')
    from urllib.parse import urlsplit
    url = string(selected.get('url'), 'url')
    try:
        parts = urlsplit(url)
        valid = parts.scheme in ('http', 'https', 'tcp') and parts.hostname and not parts.username and not parts.password and not parts.query and not parts.fragment
        parts.port
    except ValueError: valid = False
    if not valid: fail('Repository URL must be HTTP(S)/TCP without credentials, query or fragment', 'configuration_error')
    platform = string(selected.get('platform'), 'platform')
    if not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', platform): fail('platform must contain four numeric components')
    string(selected.get('username'), 'username')
    env_name = string(selected.get('password_env'), 'password_env')
    if not local_only and env_name not in os.environ: fail('Repository password environment variable is not set', 'configuration_error')
    runtime = config.get('runtime', {})
    keys(runtime, {'oscript', 'ibcmd', 'module_path','state_directory'}, 'runtime')
    def resolve(value):
        p = Path(value)
        return str((path.parent / p).resolve()) if not p.is_absolute() else str(p.resolve())
    oscript = runtime.get('oscript') or shutil.which('oscript')
    if not oscript and os.name == 'nt': oscript = str(Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'OneScript/bin/oscript.exe')
    if not local_only and (not oscript or not Path(resolve(oscript)).is_file()): fail('OneScript executable not found', 'configuration_error')
    result = dict(selected, python=sys.executable, limits=policy)
    result['state_directory']=resolve(runtime.get('state_directory',str(path.parent/'.crs-operations')))
    if oscript:result['oscript']=resolve(oscript)
    if 'repository' in result: string(result['repository'], 'repository')
    if 'cache_directory' in result: result['cache_directory'] = resolve(string(result['cache_directory'], 'cache_directory'))
    result['module_path'] = resolve(runtime.get('module_path', str(ROOT/'oscript_modules')))
    if runtime.get('ibcmd'): result['ibcmd'] = resolve(string(runtime['ibcmd'], 'ibcmd'))
    needs_compiler = action in ('workspace.init', 'changes.prepare', 'modules.prepare') or action == 'objects.read' and params['format'] == 'xml'
    if needs_compiler and not Path(result.get('ibcmd', '')).is_file(): fail('ibcmd executable not found', 'configuration_error')
    if action in ('workspace.init', 'workspace.materialize', 'changes.prepare') and 'cache_directory' not in result: fail('cache_directory is required', 'configuration_error')
    return result


def load_module_source(request, config):
    if request['action'] != 'modules.prepare':return
    sys.path.insert(0,str(SERIALIZATION))
    import resource_limits
    source=Path(request['params']['source_file'])
    budget=config.get('limits',{}).get('module_bytes',resource_limits.DEFAULTS['module_bytes'])
    if source.stat().st_size > budget:fail('source_file exceeds module_bytes')
    with source.open('rb') as stream:raw=stream.read(budget+1)
    if len(raw)>budget:fail('source_file exceeds module_bytes')
    try: value=raw.decode('utf-8-sig')
    except UnicodeError:fail('source_file must be UTF-8 BSL')
    if '\0' in value:fail('source_file contains NUL')
    request['params']['module_text']=value


def backend(request, config):
    """Secrets stay in environment; arguments only contain temporary file paths."""
    if request['action']=='workspace.materialize':
        sys.path.insert(0,str(SERIALIZATION))
        import partial_baseline
        try:return partial_baseline.materialize(dict(request['params'],cache_directory=config['cache_directory']))
        except ValueError as exc:fail(str(exc),'workspace_conflict')
    with tempfile.TemporaryDirectory(prefix='crs-cli-') as temporary:
        folder = Path(temporary)
        source, target = folder/'request.json', folder/'response.json'
        source.write_text(json.dumps(dict(request, connection={k:v for k,v in config.items() if k != 'oscript'}), ensure_ascii=False), encoding='utf-8')
        setting = folder/'oscript.cfg'
        setting.write_text('lib.additional='+config['module_path']+'\n', encoding='utf-8-sig')
        # OneScript 1.8 resolves oscript.cfg beside the entrypoint and ignores
        # OSCRIPT_CONFIG. Keep a private entrypoint there; never edit global cfg.
        bridge = folder/'bridge.os'
        code = (ROOT/'src/cli_bridge.os').read_text(encoding='utf-8-sig')
        bridge.write_text(code.replace('#Использовать ".."', '#Использовать "'+ROOT.as_posix()+'"', 1), encoding='utf-8-sig')
        env = dict(os.environ, OSCRIPT_CONFIG=str(setting), CRS_IO_PYTHON=config.get('python',sys.executable))
        if 'limits' in config:env['CRS_LIMITS_JSON']=json.dumps(config['limits'])
        if 'compiler_timeout_seconds' in config:env['CRS_COMPILER_TIMEOUT_SECONDS']=str(config['compiler_timeout_seconds'])
        cmd = [config['oscript'], str(bridge), str(source), str(target)]
        try:
            process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=config.get('operation_timeout_seconds',600),
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired:
            fail('Operation timed out; inspect state before retrying a write', 'outcome_unknown' if request['action'] in ('users.apply','commit.execute') else 'timeout')
        if not target.is_file(): fail('OneScript bridge failed; check runtime and dependencies', 'outcome_unknown' if request['action'] in ('users.apply','commit.execute') else 'backend_error')
        try: response = load_json(target.read_bytes(), 128*1024*1024)
        except CLIError:
            fail('Invalid bridge response', 'outcome_unknown' if request['action'] in ('users.apply','commit.execute') else 'backend_error')
        if process.returncode or process.stdout.strip() or process.stderr.strip() or not response.get('ok'):
            code = response.get('error', {}).get('code', 'outcome_unknown' if request['action'] in ('users.apply','commit.execute') else 'backend_error')
            messages = {'authentication_failed':'Repository authentication failed', 'user_conflict':'User state differs from expected', 'user_exists':'User name already exists', 'user_not_found':'User was not found'}
            fail(messages.get(code, 'Repository operation failed; check permissions, versions and compiler coverage'), code)
        return response['result']


def agent_commit(request,config):
    sys.path.insert(0,str(SERIALIZATION))
    import commit_artifacts
    def runner(action,params):return backend(dict(schema=1,action=action,profile=request['profile'],params=params),config)
    try:
        if request['action']=='changes.plan':return commit_artifacts.make_plan(request['params'],config,runner)
        if request['action']=='changes.commit':return commit_artifacts.execute(request['params'],config,runner)
        return commit_artifacts.status(request['params'],config,runner)
    except commit_artifacts.CommitError as exc:fail(str(exc),exc.code)


def enrich(request, result, config):
    if request['action'] in ('modules.prepare','changes.prepare') and result.get('has_changes'):
        prepared=Path(request['params']['output_directory'])/'prepared.json'
        if prepared.is_file():
            result.update(prepared_directory=str(prepared.parent),prepared_file=str(prepared),prepared_sha256=hashlib.sha256(prepared.read_bytes()).hexdigest())
    if request['action'] == 'modules.prepare':
        params = request['params']
        expected_size=len(params['module_text'].encode('utf-8'))+3
        with Path(params['source_file']).open('rb') as source:raw=source.read(expected_size+1)
        if len(raw)>expected_size:fail('Module source file changed during preparation','conflict')
        try:actual=raw.decode('utf-8-sig')
        except UnicodeError:fail('Module source file changed during preparation','conflict')
        if actual != params['module_text'] or hashlib.sha256(actual.encode('utf-8')).hexdigest() != result['plan']['after_sha256']:
            fail('Module source file changed during preparation', 'conflict')
        (Path(params['output_directory'])/'review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result
    if request['action'] == 'objects.search':
        sys.path.insert(0, str(SERIALIZATION))
        import metadata_identifiers
        labels = metadata_identifiers.class_labels()
        objects = {row['id']:row for row in result['objects']}
        def name(oid, seen=None):
            seen = set() if seen is None else seen
            if oid in seen or len(seen) >= 256 or oid not in objects: fail('Incomplete or cyclic object index', 'backend_error')
            seen.add(oid); row=objects[oid]; kind=labels.get(row['class_id'], row['class_id'])
            if row['parent_id'] == str(uuid.UUID(int=0)): return kind+'.'+row['name']
            parent=objects.get(row['parent_id'])
            if parent is None: fail('Missing object parent', 'backend_error')
            if parent['parent_id'] == str(uuid.UUID(int=0)): return kind+'.'+row['name']
            if kind.endswith('Form'): kind='Form'
            elif kind.endswith('Template'): kind='Template'
            return name(row['parent_id'], seen)+'.'+kind+'.'+row['name']
        params=request['params']; rows=[]
        for oid,row in objects.items():
            if row['deleted']: continue
            row=dict(row, kind=labels.get(row['class_id'], row['class_id']), full_name=name(oid))
            if params['query'].casefold() not in row['full_name'].casefold() and params['query'].casefold() not in row['id']: continue
            if params.get('class_id') and params['class_id']!=row['class_id']: continue
            rows.append(row)
        rows.sort(key=lambda row:(row['full_name'].casefold(),row['id']))
        offset,limit=params['offset'],params['limit']
        return dict(repository_version=result['repository_version'], total=len(rows), offset=offset,
                    objects=rows[offset:offset+limit], next_offset=offset+limit if offset+limit<len(rows) else None)
    if request['action'] == 'objects.read':
        sys.path.insert(0, str(SERIALIZATION))
        import object_changes
        native = object_changes.compare(dict(object_id=request['params']['object_id'], after=result['snapshots'][0]))
        output = dict(description=result['description'], repository_version=result['repository_version'], native=native)
        if request['params']['format'] == 'xml':
            import object_xml_changes
            try:
                if result.get('context_unavailable'): raise ValueError('Context unavailable')
                with tempfile.TemporaryDirectory(prefix='crs-cli-view-') as temporary:
                    files = object_xml_changes.export(Path(config['ibcmd']), config['platform'], result, request['params']['object_id'], Path(temporary))
                    output['representation'] = dict(status='available', files=[dict(path=name, **object_changes.value(raw)) for name,raw in sorted(files.items())])
            except (ValueError, RuntimeError, OSError, subprocess.SubprocessError):
                output['representation'] = dict(status='unavailable', reason='Compiler cannot export the selected object with its available context; native contents are present')
        return output
    if request['action'] == 'changes.prepare':
        sys.path.insert(0, str(SERIALIZATION))
        import configuration_export as export
        import xml_compare
        _, before, _, _ = export.inventory(result['baseline_directory'])
        _, after, _, _ = export.inventory(request['params']['directory'])
        if export.fingerprint(before)!=result['plan']['baseline_fingerprint'] or export.fingerprint(after)!=result['plan']['target_fingerprint']:
            fail('XML sources changed after preparation; review is invalid', 'conflict')
        changes = []
        for name in sorted(before.keys() | after.keys()):
            if xml_compare.file_equal(name, before.get(name), after.get(name)): continue
            row = dict(path=name, action='create' if name not in before else 'delete' if name not in after else 'modify')
            try:
                left = before.get(name, b'').decode('utf-8-sig'); right = after.get(name, b'').decode('utf-8-sig')
                if '\0' in left+right: raise UnicodeError()
                diff = ''.join(difflib.unified_diff(left.splitlines(True), right.splitlines(True), fromfile='before/'+name, tofile='after/'+name))
                row.update(diff=diff[:200000], diff_truncated=len(diff)>200000)
            except UnicodeError: row['binary'] = True
            changes.append(row)
        result.update(files=changes, captured=False, committed=False)
        (Path(request['params']['output_directory'])/'review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


class Parser(argparse.ArgumentParser):
    def error(self, message): fail('Invalid CLI arguments')


def main(argv=None):
    action = None
    try:
        parser = Parser(add_help=False)
        parser.add_argument('--config'); parser.add_argument('--request', default='-'); parser.add_argument('--help', action='store_true')
        args = parser.parse_args(argv)
        if args.help:
            result = dict(actions=list(ACTIONS), usage='python tools/crs.py --config CONFIG --request REQUEST.json (or - for stdin)', schema=1)
        else:
            if not args.config: fail('--config is required')
            raw = sys.stdin.buffer.read(8*1024*1024+1) if args.request=='-' else Path(args.request).read_bytes()
            request = validate(load_json(raw)); action = request['action']
            config = configuration(args.config, request['profile'], action, request['params'])
            load_module_source(request, config)
            if action in ('changes.prepare', 'modules.prepare'): Path(request['params']['output_directory']).mkdir(parents=True, exist_ok=False)
            import resource_limits
            with resource_limits.scope(config['limits']):
                if action in ('changes.plan','changes.commit','changes.status'):result=agent_commit(request,config)
                else:result = enrich(request, backend(request, config), config)
        response = dict(schema=1, ok=True, action=action or 'help', result=result)
        encoded = json.dumps(response, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode('utf-8')) > 32*1024*1024: fail('Result exceeds 32 MiB; use a workspace', 'output_too_large')
        sys.stdout.buffer.write((encoded+'\n').encode('utf-8')); return 0
    except CLIError as error:
        response = dict(schema=1, ok=False, action=action, error=dict(code=error.code, message=str(error)))
    except Exception:
        response = dict(schema=1, ok=False, action=action, error=dict(code='local_error', message='Local operation failed; check paths, input and runtime'))
    sys.stdout.buffer.write((json.dumps(response, ensure_ascii=False)+'\n').encode('utf-8')); return 1
