"""MCP framing, CLI delegation and write boundaries, without a shared repository."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import agent_cli
import agent_mcp as mcp


def request(method, request_id=1, **params):
    return dict(jsonrpc='2.0', id=request_id, method=method, params=params)


def start(server):
    server.receive(request('initialize', protocolVersion=mcp.PROTOCOL, capabilities={}, clientInfo=dict(name='test', version='1')))
    server.receive(dict(jsonrpc='2.0', method='notifications/initialized'))


class MCPTests(unittest.TestCase):
    def server(self, runner=None, writes=False, configuration_writes=False):
        output = io.BytesIO()
        server = mcp.Server(runner or (lambda r: dict(schema=1, ok=True, action=r['action'], result=r['params'])), output, writes,configuration_writes)
        self.addCleanup(server.pool.shutdown, wait=True)
        return server, output

    def messages(self, output):
        return [json.loads(line) for line in output.getvalue().splitlines()]

    def test_catalog_matches_cli_and_disables_writes_by_default(self):
        self.assertEqual({name[4:].replace('_', '.', 1) for name in mcp.tool_definitions(True,True)}, set(agent_cli.ACTIONS))
        self.assertNotIn('crs_users_apply', mcp.tool_definitions())
        self.assertNotIn('crs_changes_commit', mcp.tool_definitions())
        self.assertIn('crs_changes_commit', mcp.tool_definitions(False,True))
        self.assertNotIn('crs_users_apply', mcp.tool_definitions(False,True))
        self.assertTrue(mcp.tool_definitions()['crs_users_plan']['annotations']['readOnlyHint'])
        self.assertFalse(mcp.tool_definitions()['crs_changes_prepare']['annotations']['readOnlyHint'])
        self.assertTrue(mcp.tool_definitions(True,True)['crs_users_apply']['annotations']['destructiveHint'])
        for tool in mcp.tool_definitions(True,True).values():
            self.assertFalse(tool['inputSchema']['additionalProperties'])
            self.assertIn('profile', tool['inputSchema']['required'])
            self.assertNotIn('password', tool['inputSchema']['properties'])

    def test_lifecycle_unknown_methods_notifications_and_negotiation(self):
        server, output = self.server()
        server.receive(request('tools/list'))
        server.receive(request('initialize', 2, protocolVersion='future', capabilities={}, clientInfo={}))
        server.receive(request('tools/list', 3))
        server.receive(dict(jsonrpc='2.0', method='notifications/initialized'))
        server.receive(dict(jsonrpc='2.0', method='unknown-notification'))
        server.receive(request('tools/list', 4))
        server.receive(request('arbitrary/method', 5))
        results = self.messages(output)
        self.assertEqual(len(results), 5)
        self.assertEqual(results[0]['error']['code'], -32600)
        self.assertEqual(results[1]['result']['protocolVersion'], mcp.PROTOCOL)
        self.assertEqual(results[2]['error']['code'], -32600)
        self.assertEqual(len(results[3]['result']['tools']), 11)
        self.assertEqual(results[4]['error']['code'], -32601)

    def test_tools_delegate_json_envelopes_and_preserve_structured_errors(self):
        calls = []
        def run(r):
            calls.append(copy.deepcopy(r))
            try:
                agent_cli.validate(r)
                return dict(schema=1, ok=True, action=r['action'], result=dict(query=r['params']['query']))
            except agent_cli.CLIError as e:
                return mcp.failure(r['action'], e.code, str(e))
        server, output = self.server(run)
        start(server)
        server.receive(request('tools/call', 2, name='crs_objects_search', arguments=dict(profile='lab', query='Обмен')))
        server.receive(request('tools/call', 3, name='crs_objects_read', arguments=dict(profile='lab', object_id='bad')))
        server.pool.shutdown(wait=True)
        results = {v['id']: v for v in self.messages(output)}
        self.assertEqual(calls[0], dict(schema=1, action='objects.search', profile='lab', params=dict(query='Обмен')))
        value = results[2]['result']
        self.assertEqual(value['structuredContent'], json.loads(value['content'][0]['text']))
        self.assertFalse(value['isError'])
        self.assertTrue(results[3]['result']['isError'])
        self.assertEqual(results[3]['result']['structuredContent']['error']['code'], 'invalid_request')

    def test_disabled_write_cannot_be_invoked_by_name(self):
        run = mock.Mock()
        server, output = self.server(run)
        start(server)
        server.receive(request('tools/call', 2, name='crs_users_apply', arguments=dict(profile='lab', execute=True)))
        server.receive(request('tools/call', 3, name='crs_changes_commit', arguments=dict(profile='lab', execute=True)))
        self.assertEqual(self.messages(output)[-1]['error']['code'], -32602)
        run.assert_not_called()

    def test_configuration_commit_delegates_exact_approval_hash(self):
        calls=[]
        def run(r):calls.append(r);return dict(schema=1,ok=True,action=r['action'],result=dict(committed=True,version=2))
        server,output=self.server(run,configuration_writes=True);start(server)
        server.receive(request('tools/call',2,name='crs_changes_commit',arguments=dict(profile='lab',plan_file='plan.json',approved_plan_sha256='a'*64,execute=True)))
        server.pool.shutdown(wait=True)
        self.assertEqual(calls,[dict(schema=1,action='changes.commit',profile='lab',params=dict(plan_file='plan.json',approved_plan_sha256='a'*64,execute=True))])
        self.assertEqual(self.messages(output)[-1]['result']['structuredContent']['result']['version'],2)

    def test_enabled_writes_still_pass_cli_validation(self):
        def run(r):
            try:
                agent_cli.validate(r)
            except agent_cli.CLIError as e:
                return mcp.failure(r['action'], e.code, str(e))
            self.fail('Missing execute/expected must not pass validation')
        server, output = self.server(run, writes=True)
        start(server)
        server.receive(request('tools/call', 2, name='crs_users_apply', arguments=dict(profile='lab', operation='delete', user_id='11111111-1111-1111-1111-111111111111')))
        server.pool.shutdown(wait=True)
        self.assertTrue(self.messages(output)[-1]['result']['isError'])

    def test_ping_is_responsive_and_queued_call_can_be_cancelled(self):
        begun, release = threading.Event(), threading.Event()
        calls = []
        def run(r):
            calls.append(r)
            begun.set()
            release.wait(5)
            return dict(schema=1, ok=True, action=r['action'], result={})
        server, output = self.server(run)
        self.addCleanup(release.set)
        start(server)
        server.receive(request('tools/call', 2, name='crs_connect', arguments=dict(profile='lab')))
        self.assertTrue(begun.wait(2))
        server.receive(request('tools/call', 3, name='crs_connect', arguments=dict(profile='lab')))
        server.receive(request('tools/call', 2, name='crs_connect', arguments=dict(profile='lab')))
        server.receive(request('ping', 4))
        server.receive(dict(jsonrpc='2.0', method='notifications/cancelled', params=dict(requestId=3)))
        interim = self.messages(output)
        self.assertTrue(any(m.get('id') == 4 and m.get('result') == {} for m in interim))
        self.assertTrue(any(m.get('id') == 2 and 'error' in m for m in interim))
        release.set()
        server.pool.shutdown(wait=True)
        self.assertEqual(len(calls), 1)
        self.assertNotIn(3, [m.get('id') for m in self.messages(output)])

    def test_stdio_recovers_after_parse_error_and_rejects_batches_and_bad_ids(self):
        server, output = self.server()
        lines = [b'{bad}\n', b'[]\n', b'{"jsonrpc":"2.0","id":true,"method":"ping"}\n',
                 json.dumps(request('ping', 9)).encode() + b'\n']
        server.serve(io.BytesIO(b''.join(lines)))
        messages = self.messages(output)
        self.assertEqual([m['error']['code'] for m in messages[:3]], [-32700, -32600, -32600])
        self.assertEqual(messages[-1], dict(jsonrpc='2.0', id=9, result={}))

    def test_cli_subprocess_has_fixed_config_workspace_and_no_shell(self):
        runner = mcp.CLIRunner('profile.json', '.', 12)
        response = dict(schema=1, ok=True, action='connect', result=dict(connected=True))
        with mock.patch.object(mcp.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(response).encode(), b'private diagnostics')) as run:
            self.assertEqual(runner(dict(schema=1, action='connect', profile='lab', params={})), response)
        args, kwargs = run.call_args
        self.assertEqual(args[0][-2:], ['--config', runner.config])
        self.assertEqual(kwargs['cwd'], runner.workspace)
        self.assertNotIn('shell', kwargs)
        self.assertEqual(json.loads(kwargs['input'])['profile'], 'lab')

    def test_timeout_or_malformed_write_result_is_uncertain_and_sanitized(self):
        runner = mcp.CLIRunner('profile.json', '.')
        for outcome in (subprocess.TimeoutExpired(['secret'], 1), subprocess.CompletedProcess([], 0, b'secret', b'secret')):
            with mock.patch.object(mcp.subprocess, 'run', **({'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome})):
                for action in ('users.apply','changes.commit'):
                    result = runner(dict(action=action))
                    self.assertEqual(result['error']['code'], 'outcome_unknown')
                    self.assertNotIn('secret', json.dumps(result))

    def test_actual_entrypoint_stdout_is_only_jsonrpc(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config.json'
            config.write_text('{"schema":1,"repositories":{}}', encoding='utf-8')
            messages = [request('initialize', protocolVersion=mcp.PROTOCOL, capabilities={}, clientInfo={}),
                        dict(jsonrpc='2.0', method='notifications/initialized'), request('tools/list', 2)]
            done = subprocess.run([sys.executable, str(ROOT / 'tools/crs_mcp.py'), '--config', str(config), '--workspace', tmp],
                                  input=b''.join(json.dumps(m).encode() + b'\n' for m in messages),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            self.assertEqual(done.returncode, 0, done.stderr)
            results = [json.loads(line) for line in done.stdout.splitlines()]
            self.assertEqual(len(results), 2)
            self.assertEqual(len(results[-1]['result']['tools']), 11)
            self.assertEqual(done.stderr, b'')

    def test_real_cli_validation_errors_survive_the_adapter(self):
        # No config/server is necessary: validation fails before opening them.
        response = mcp.CLIRunner('missing.json', ROOT)(dict(schema=1, action='users.apply', profile='lab',
                                                         params=dict(operation='create', name='bot', password_env='UNSET')))
        self.assertEqual(response['action'], 'users.apply')
        self.assertEqual(response['error']['code'], 'invalid_request')
        self.assertIn('execute', response['error']['message'])

    def test_empty_password_environment_survives_the_cli_subprocess(self):
        # On Windows os.putenv(name, '') removes the native environment entry;
        # Python's os.environ still retains it. Explicit env preserves that entry
        # when launching the CLI. Stop at runtime validation; no server is contacted.
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, CRS_MCP_EMPTY_PASSWORD=''):
            config = Path(tmp) / 'config.json'
            config.write_text(json.dumps(dict(schema=1, repositories=dict(lab=dict(
                url='tcp://127.0.0.1:1/unused', platform='8.5.1.1529', username='reader',
                password_env='CRS_MCP_EMPTY_PASSWORD')), runtime=dict(oscript=str(Path(tmp) / 'missing.exe')))), encoding='utf-8')
            result = mcp.CLIRunner(config, tmp)(dict(schema=1, action='connect', profile='lab', params={}))
            self.assertEqual(result['error']['message'], 'OneScript executable not found')


if __name__ == '__main__':
    unittest.main()
