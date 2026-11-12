"""MCP 2025-11-25 stdio adapter. Repository operations stay in the JSON CLI.

Only one CLI process runs at a time; the reader remains available for ping and
cancellation. Cancelling a running call does not roll back its side effects.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from agent_cli import ACTIONS, CLIError, ROOT, load_json

PROTOCOL = '2025-11-25'
MAX_MESSAGE = 8 * 1024 * 1024
MAX_RESULT = 32 * 1024 * 1024


def obj(properties, required=()):
    return dict(type='object', properties=properties, required=list(required), additionalProperties=False)


def text_schema(**extra):
    return dict(type='string', minLength=1, **extra)


def tool_definitions(allow_user_writes=False,allow_configuration_writes=False):
    """Explicit schemas describe the CLI contract, never credentials or config paths."""
    uuid = text_schema(format='uuid')
    user = dict(operation=dict(type='string', enum=['create', 'update', 'delete', 'restore']),
                user_id=uuid, name=text_schema(),
                role=dict(type='string', enum=['read_only', 'developer', 'developer_extended', 'admin']),
                password_env=text_schema(description='Name of an environment variable inherited by the server; never a password.'))
    expected = obj(dict(id=uuid, name=dict(type='string'), role=dict(type='string'),
                        rights=dict(type='string'), deleted=dict(type='boolean')),
                   ('id', 'name', 'role', 'rights', 'deleted'))
    rows = [
        ('connect', 'Check repository authorization and current version. Does not retain a session.', {}, (), True),
        ('objects.search', 'Find current object descriptors by name/UUID and metadata kind. Not BSL full-text search.',
         dict(query=dict(type='string'), kind=text_schema(), class_id=uuid,
              offset=dict(type='integer', minimum=0, maximum=10000000),
              limit=dict(type='integer', minimum=1, maximum=1000)), (), True),
        ('objects.read', 'Read one current object. XML/BSL conversion may be unavailable; inspect representation.status. Native streams remain available.',
         dict(object_id=uuid, format=dict(type='string', enum=['xml', 'native'], default='xml')), ('object_id',), True),
        ('workspace.init', 'Initialize a local XML baseline. allow_partial creates an explicitly incomplete view over the complete CF and a sparse working directory; whole-configuration preparation is unavailable for it. No capture or commit.',
         dict(directory=text_schema(),allow_partial=dict(type='boolean',default=False)), ('directory',), False),
        ('workspace.materialize', 'Copy selected owners from a frozen partial baseline to its sparse working directory. Existing local edits are never overwritten. Missing XML does not mean deletion. Local files only; no repository or compiler calls.',
         dict(baseline_id=text_schema(pattern='^[0-9a-f]{32}$'),object_ids=dict(type='array',items=uuid,minItems=1,maxItems=1000,uniqueItems=True)),
         ('baseline_id','object_ids'), False),
        ('changes.prepare', 'Compile a complete XML directory into a local packet and review. Output must be a new separate directory. No capture or configuration commit.',
         dict(directory=text_schema(), baseline_directory=text_schema(), output_directory=text_schema()),
         ('directory', 'output_directory'), False),
        ('modules.prepare', 'Prepare one existing standalone Module stream from its addressed snapshot using ibcmd. No full CF, capture or commit. expected_source_sha256 is SHA256 of the original UTF-8 BSL without BOM, with original line endings. Output must be a new separate directory.',
         dict(object_id=uuid, module_path=text_schema(), source_file=text_schema(),
              expected_source_sha256=text_schema(pattern='^[0-9a-f]{64}$'), output_directory=text_schema()),
         ('object_id', 'module_path', 'source_file', 'expected_source_sha256', 'output_directory'), False),
        ('users.list', 'List repository users with roles and raw rights, excluding passwords and hashes.', {}, (), True),
        ('users.plan', 'Plan a user create/update/delete/restore without writing. Review before/after and obtain approval before apply.',
         user, ('operation',), True),
        ('changes.plan','Build a concrete commit plan from a prepared packet and review. Read-only repository preflight, no capture or commit. Show target, user, objects, diff and comment to the human. Labels are currently not written.',
         dict(prepared_directory=text_schema(),comment=text_schema(),label=text_schema()),('prepared_directory','comment'),False),
        ('changes.status','Inspect a commit attempt and current repository descriptors/captures. No capture, release or replay. Use after an uncertain result; never retry the write automatically.',
         dict(plan_file=text_schema(),plan_sha256=text_schema(pattern='^[0-9a-f]{64}$')),('plan_file','plan_sha256'),True),
    ]
    if allow_configuration_writes:
        rows.append(('changes.commit','WRITE: execute one specifically human-approved commit plan once, including capture and release of only this operation\'s captures. Require explicit approval of the exact plan_sha256, repository, objects, diff and comment. Enabling this tool is not permission. Inspect status after any uncertain outcome; never resend automatically.',
             dict(plan_file=text_schema(),approved_plan_sha256=text_schema(pattern='^[0-9a-f]{64}$'),execute=dict(type='boolean',const=True)),
             ('plan_file','approved_plan_sha256','execute'),False))
    if allow_user_writes:
        rows.append(('users.apply', 'WRITE: apply an explicitly approved user plan once. Pass before as expected for an existing user. On outcome_unknown inspect state before retrying.',
                     dict(user, execute=dict(type='boolean', const=True), expected=expected), ('operation', 'execute'), False))
    result = {}
    for action, description, properties, required, read_only in rows:
        name = 'crs_' + action.replace('.', '_')
        result[name] = dict(name=name, description=description,
                            inputSchema=obj(dict(profile=text_schema(), **properties), ('profile',) + required),
                            annotations=dict(readOnlyHint=read_only,
                                             destructiveHint=action in ('users.apply','changes.commit'),
                                             idempotentHint=read_only, openWorldHint=True))
    return result


def tool_result(response):
    return dict(content=[dict(type='text', text=json.dumps(response, ensure_ascii=False))],
                structuredContent=response, isError=not response.get('ok', False))


def failure(action, code, message):
    return dict(schema=1, ok=False, action=action, error=dict(code=code, message=message))


class CLIRunner:
    def __init__(self, config, workspace, timeout=900):
        self.config = str(Path(config).resolve())
        self.workspace = str(Path(workspace).resolve())
        self.timeout = timeout

    def __call__(self, request):
        action = request['action']
        try:
            # No shell, no secrets on argv; stdout belongs to the child until parsed.
            done = subprocess.run([sys.executable, str(ROOT / 'tools/crs.py'), '--config', self.config],
                                  input=json.dumps(request, ensure_ascii=False).encode('utf-8'),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  cwd=self.workspace, timeout=self.timeout, env=dict(os.environ))
            response = load_json(done.stdout, limit=MAX_RESULT)
            if (not isinstance(response, dict) or response.get('schema') != 1
                    or type(response.get('ok')) is not bool
                    or response.get('action') not in (action, None)
                    or (response['ok'] and response.get('action') != action)
                    or done.returncode != (0 if response['ok'] else 1)
                    or ('result' if response['ok'] else 'error') not in response):
                raise ValueError('Invalid CLI response')
            # CLI validation can fail before assigning action (then action=null).
            # Retain that error instead of replacing it with a transport failure.
            response['action'] = action
            return response
        except (OSError, ValueError, subprocess.TimeoutExpired):
            # For writes, a lost response is not proof that the operation failed.
            if action in ('users.apply','changes.commit'):
                return failure(action, 'outcome_unknown', 'CLI outcome unknown; inspect operation status before any retry.')
            return failure(action, 'cli_failed', 'CLI failed or timed out; no subprocess output is disclosed.')


class Server:
    def __init__(self, runner, output, allow_user_writes=False,allow_configuration_writes=False):
        self.runner = runner
        self.output = output
        self.tools = tool_definitions(allow_user_writes,allow_configuration_writes)
        self.initialized = False
        self.ready = False
        self.lock = threading.RLock()
        self.pending = {}
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='crs-cli')

    def send(self, message):
        raw = (json.dumps(dict(jsonrpc='2.0', **message), ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
        with self.lock:
            self.output.write(raw)
            self.output.flush()

    def error(self, request_id, code, message):
        self.send(dict(id=request_id, error=dict(code=code, message=message)))

    def call(self, request_id, action, arguments):
        try:
            # Validation lives in the CLI. In particular, paths resolve in the fixed
            # workspace of that process rather than the MCP host's working directory.
            request = dict(schema=1, action=action, profile=arguments.get('profile'),
                           params={k: v for k, v in arguments.items() if k != 'profile'})
            response = self.runner(request)
            self.send(dict(id=request_id, result=tool_result(response)))
        except Exception:
            code = 'outcome_unknown' if action in ('users.apply','changes.commit') else 'cli_failed'
            self.send(dict(id=request_id, result=tool_result(failure(action, code, 'Tool execution failed; inspect state before retrying a write.'))))
        finally:
            with self.lock:
                self.pending.pop(request_id, None)

    def receive(self, message):
        if (not isinstance(message, dict) or message.get('jsonrpc') != '2.0'
                or not isinstance(message.get('method'), str)
                or ('id' in message and type(message['id']) not in (str, int))):
            self.error(None, -32600, 'Invalid JSON-RPC request')
            return
        method = message['method']
        request_id = message.get('id')
        params = message.get('params', {})
        if 'id' not in message:
            if method == 'notifications/initialized' and self.initialized:
                self.ready = True
            elif method == 'notifications/cancelled' and isinstance(params, dict):
                cancelled = params.get('requestId')
                if type(cancelled) in (str, int):
                    with self.lock:
                        future = self.pending.get(cancelled)
                        # Running calls finish: killing a CLI cannot roll back writes
                        # or reliably terminate all compiler/OneScript children.
                        if future and future.cancel():
                            self.pending.pop(cancelled, None)
            return
        if not isinstance(params, dict):
            self.error(request_id, -32602, 'params must be an object')
            return
        with self.lock:
            if request_id in self.pending:
                self.error(request_id, -32600, 'Request ID is already in use')
                return
        if method == 'ping':
            self.send(dict(id=request_id, result={}))
        elif method == 'initialize':
            if (self.initialized or not isinstance(params.get('protocolVersion'), str)
                    or not isinstance(params.get('capabilities'), dict)
                    or not isinstance(params.get('clientInfo'), dict)):
                self.error(request_id, -32602, 'Invalid initialization')
                return
            self.initialized = True
            self.send(dict(id=request_id, result=dict(protocolVersion=PROTOCOL, capabilities=dict(tools={}),
                      serverInfo=dict(name='crs-api', version='0.2.1'),
                      instructions='Use named profiles. Prepare locally, create a concrete changes.plan, and obtain explicit human approval of its exact hash before changes.commit. Tool availability does not grant write permission. Review user plans before users.apply. Never retry uncertain writes; inspect changes.status.')))
        elif not self.ready:
            self.error(request_id, -32600, 'Initialize the MCP session first')
        elif method == 'tools/list':
            if params.get('cursor') is not None:
                self.error(request_id, -32602, 'Pagination cursor is not supported')
            else:
                self.send(dict(id=request_id, result=dict(tools=list(self.tools.values()))))
        elif method == 'tools/call':
            name = params.get('name')
            if not isinstance(name, str) or name not in self.tools:
                self.error(request_id, -32602, 'Unknown or disabled tool')
                return
            arguments = params.get('arguments', {})
            if not isinstance(arguments, dict):
                self.error(request_id, -32602, 'arguments must be an object')
                return
            action = name[4:].replace('_', '.', 1)
            if action not in ACTIONS:
                self.error(request_id, -32602, 'Unknown action')
                return
            with self.lock:
                if len(self.pending) >= 8:
                    self.error(request_id, -32000, 'Tool queue is full')
                else:
                    # Hold lock until registered: an immediate result must not leave
                    # a completed future in pending or reuse an active request ID.
                    self.pending[request_id] = self.pool.submit(self.call, request_id, action, arguments)
        else:
            self.error(request_id, -32601, 'Method not found')

    def serve(self, source):
        try:
            while True:
                line = source.readline(MAX_MESSAGE + 1)
                if not line:
                    break
                if len(line) > MAX_MESSAGE:
                    self.error(None, -32600, 'Message exceeds size limit')
                    break
                try:
                    message = load_json(line)
                except CLIError:
                    self.error(None, -32700, 'Invalid UTF-8 JSON')
                    continue
                self.receive(message)
        finally:
            # Do not start queued operations after the host disconnected.
            self.pool.shutdown(wait=True, cancel_futures=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='CRS API MCP stdio server (protocol ' + PROTOCOL + ').')
    parser.add_argument('--config', required=True, help='Fixed CLI profiles/runtime JSON file')
    parser.add_argument('--workspace', default='.', help='Base directory for relative tool paths')
    parser.add_argument('--allow-user-writes', action='store_true', help='Expose users.apply; explicit approval is still required')
    parser.add_argument('--allow-configuration-writes',action='store_true',help='Expose changes.commit; approval of each exact plan is still required')
    parser.add_argument('--timeout', type=int, default=900, help='Maximum seconds per CLI process (default 900)')
    args = parser.parse_args(argv)
    if not Path(args.config).is_file() or not Path(args.workspace).is_dir() or args.timeout < 1:
        parser.error('Config/workspace must exist and timeout must be positive')
    try:
        Server(CLIRunner(args.config, args.workspace, args.timeout), sys.stdout.buffer,
               args.allow_user_writes,args.allow_configuration_writes).serve(sys.stdin.buffer)
    except (BrokenPipeError, KeyboardInterrupt):
        return 1
    return 0
