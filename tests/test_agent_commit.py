"""Reviewed immutable packets and actual OneScript commits to loopback only."""
import base64
import copy
import json
import os
from pathlib import Path
import socketserver
import sys
import tempfile
import threading
import unittest
import uuid
from unittest import mock
from xml.etree import ElementTree as E

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'src'/'Сериализация')]
import agent_cli as cli
import commit_artifacts as api
import native_metadata as s
import test_module_commit as module_tests
from test_repository_cache import snapshot,CHILD,OLD,REPO,NEW
from test_version_labels import OSCRIPT,Q,END

USER='77777777-7777-4777-8777-777777777777'
ZERO=str(uuid.UUID(int=0))


def artifact(folder,url='tcp://127.0.0.1:1/test'):
    case=module_tests.ModuleCommitTests();case.setUp()
    try:
        compiled={}
        def overlay(compiler,*args):
            reply=case.overlay(compiler,*args);compiled.update(module_tests.ibcmd_backend.read_fragment(args[3]));return reply
        result=case.prepare(overlay=overlay)
        original=case.request['source']
        source=dict(original,version=original['version_number'],own_version=original['self_version_number'],deleted=False)
        result=dict(result,version_code='Synthetic version',version_code_resolved=True)
        packet={k:result[k] for k in ('repository_version','repository','platform','version_code','version_code_resolved',
                                     'changed_ids','new_ids','removed_ids','descriptions','requested','externals','verification')}
        for row in packet['descriptions']+packet['requested']:row.update(version=0,own_version=0,deleted=False)
        folder.mkdir();(folder/'packet.bin').write_bytes(base64.b64decode(result['data']))
        api.save(dict(directory=str(folder),binding=dict(url=url,repository='test',platform='8.5.1.1529',repository_id=REPO),
                      sources=[source],packet=packet))
        (folder/'review.json').write_text(json.dumps(dict(has_changes=True,diff=result['review']['diff'])),encoding='utf-8')
        result.update(fixture_streams=dict(case.streams,**{case.name:compiled[case.name]}),fixture_body=case.body,fixture_saved=case.saved)
        return source,result
    finally:case.doCleanups()


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        self.prepared=self.folder/'prepared';self.source,self.native=artifact(self.prepared)
        self.config=dict(url='tcp://127.0.0.1:1/test',repository='test',platform='8.5.1.1529',username='test',state_directory=str(self.folder/'state'))
        self.probe=dict(repository_id=REPO,user_id=USER,configuration_version='Synthetic version',captures=[],ready=True,conflicts=[])

    def plan(self,**kwargs):return api.make_plan(dict(prepared_directory=str(self.prepared),comment='Synthetic commit',**kwargs),self.config,lambda *_:self.probe)
    def execute(self,plan,runner):return api.execute(dict(plan_file=plan['plan_file'],approved_plan_sha256=plan['plan_sha256'],execute=True),self.config,runner)

    def test_exact_approval_and_packet_review_metadata_tamper_prevent_backend_calls(self):
        for name in ('plan','packet.bin','review.json','prepared.json'):
            with self.subTest(name=name):
                plan=self.plan();path=Path(plan['plan_file']) if name=='plan' else self.prepared/name
                original=path.read_bytes();path.write_bytes(original+b' ');runner=mock.Mock()
                try:
                    with self.assertRaises(api.CommitError):self.execute(plan,runner)
                    runner.assert_not_called()
                finally:path.write_bytes(original)

    def test_execute_required_and_same_packet_under_another_plan_cannot_resend(self):
        plan=self.plan();runner=mock.Mock(return_value=dict(committed=True,outcome_unknown=False))
        with self.assertRaisesRegex(api.CommitError,'execute'):
            api.execute(dict(plan_file=plan['plan_file'],approved_plan_sha256=plan['plan_sha256']),self.config,runner)
        result=self.execute(plan,runner);self.assertFalse(result['already_executed'])
        self.assertTrue(self.execute(plan,runner)['already_executed']);self.assertEqual(runner.call_count,1)
        with self.assertRaisesRegex(api.CommitError,'already has'):self.execute(self.plan(),runner)
        self.assertEqual(runner.call_count,1)

    def test_lost_process_and_recorded_unknown_outcomes_never_resend(self):
        plan=self.plan();runner=mock.Mock(side_effect=RuntimeError('lost process'))
        with self.assertRaises(RuntimeError):self.execute(plan,runner)
        with self.assertRaises(api.CommitError) as raised:self.execute(plan,runner)
        self.assertEqual(raised.exception.code,'outcome_unknown');self.assertEqual(runner.call_count,1)

    def test_status_keeps_local_evidence_when_prepared_files_have_disappeared(self):
        plan=self.plan();self.execute(plan,lambda *_:dict(committed=True,outcome_unknown=False))
        (self.prepared/'packet.bin').unlink();runner=mock.Mock()
        result=api.status(dict(plan_file=plan['plan_file'],plan_sha256=plan['plan_sha256']),self.config,runner)
        self.assertTrue(result['result']['committed']);self.assertIn('observation_error',result);runner.assert_not_called()

    def test_jira_comment_label_and_conflicts_are_reviewed(self):
        plan=api.make_plan(dict(prepared_directory=str(self.prepared),comment='#DEMO-42: Synthetic change'),self.config,lambda *_:self.probe)
        self.assertEqual(plan['plan']['label'],dict(name='#DEMO-42',status='not_supported'))
        with self.assertRaises(api.CommitError):api.make_plan(dict(prepared_directory=str(self.prepared),comment='DEMO-42: Missing hash'),self.config,lambda *_:self.probe)
        self.probe.update(ready=False,conflicts=[CHILD]);runner=mock.Mock()
        with self.assertRaises(api.CommitError):self.execute(self.plan(),runner)
        runner.assert_not_called()


@unittest.skipUnless(OSCRIPT and Path(OSCRIPT).is_file(),'OneScript unavailable')
class LoopbackCommitTests(unittest.TestCase):
    def run_case(self,fault='',owned=False):
        calls=[];errors=[];state=dict(commits=0,captured=owned,captures=0,releases=0)
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp);prepared=work/'prepared'
            source,native=artifact(prepared)
            after=dict(source,**native['descriptions'][0]);after.update(version=2,own_version=2,deleted=False)
            # A full addressed server snapshot, including the preserved external.
            streams=native['fixture_streams'];body=native['fixture_body'];saved=copy.deepcopy(native['fixture_saved'])
            saved[0][5]=saved[0][6]=s.atom(2)
            saved[0][7]=s.atom(uuid.UUID(bytes_le=bytes.fromhex(after['original'])[:16]))
            saved[0][8]=s.atom(uuid.UUID(bytes_le=bytes.fromhex(after['local'])[:16]))
            snap=snapshot(CHILD,saved,body if fault!='readback' else b'{1,"wrong"}',streams)
            test=self
            class Handler(socketserver.BaseRequestHandler):
                def handle(inner):
                    try:
                        inner.request.settimeout(10);inner.request.sendall(bytes.fromhex('53f5c61a7b'));raw=b''
                        while not raw.endswith(END):
                            part=inner.request.recv(65536)
                            if not part:raise AssertionError('Truncated request')
                            raw+=part
                        request=E.fromstring(raw.split(b'\r\n\r\n',1)[1][:-4]);method=request.get('name');calls.append(method)
                        params=request.find(Q+'params');root=E.Element(Q+'call_return')
                        def value(node,key,v):return E.SubElement(node,Q+key,value=str(v).lower() if isinstance(v,bool) else str(v))
                        if method=='DevDepot_depotInfo':
                            value(E.SubElement(E.SubElement(root,Q+'info'),Q+'info'),'depotID',REPO)
                        elif method=='UserManager_depotUserByName':
                            user=E.SubElement(root,Q+'user');info=E.SubElement(user,Q+'info')
                            for k,v in dict(id=USER,name='test',password='synthetic',rights='1').items():value(info,k,v)
                            value(user,'online',False);value(user,'removed',False)
                        elif method=='DevDepot_latestVerID':value(root,'verID',NEW if state['commits'] else OLD)
                        elif method=='DevDepot_devObjectsStatistic':
                            r=after if state['commits'] else source;group=E.SubElement(root,Q+'statMap')
                            item=E.SubElement(group,Q+'value');value(item,'first',CHILD);info=E.SubElement(item,Q+'second')
                            for k,v in dict(verNum=r['version'],revised=state['captured'],revisorID=USER if state['captured'] else ZERO,reviseDate='2026-01-01T00:00:00').items():value(info,k,v)
                        elif method=='DevDepot_versionObjects':
                            r=after if state['commits'] else source;group=E.SubElement(root,Q+'objects')
                            item=E.SubElement(group,Q+'value');value(item,'first',CHILD);info=E.SubElement(E.SubElement(item,Q+'second'),Q+'info')
                            ident=E.SubElement(info,Q+'_super');value(ident,'id',CHILD);value(ident,'classID',r['class_id'])
                            for k,f in [('name','name'),('pos','pos'),('verNum','version'),('selfVerNum','own_version'),('parentID','parent_id'),('ownerID','owner_id')]:value(info,k,r[f])
                            versions=E.SubElement(info,Q+'version');value(versions,'original',r['original']);value(versions,'local',r['local']);value(info,'removed',False)
                        elif method=='DevDepot_reviseDevObjects':
                            capture=params.find(Q+'revise').get('value')=='true';state['captured']=capture;state['captures' if capture else 'releases']+=1
                            E.SubElement(root,Q+'exc');result=E.SubElement(root,Q+'result');E.SubElement(result,Q+'unprocessed')
                            value(E.SubElement(E.SubElement(result,Q+'requested'),Q+'value'),'first',CHILD)
                        elif method=='DevDepot_commitObjects':
                            state['commits']+=1
                            test.assertEqual(params.find(Q+'code').get('value'),'Synthetic version')
                            test.assertEqual(params.find(Q+'comment').text,'Synthetic commit')
                            test.assertEqual(params.find(Q+'clientVerID').get('value'),OLD)
                            if fault=='lost_reply':return
                            E.SubElement(root,Q+'exc');result=E.SubElement(root,Q+'result');E.SubElement(result,Q+'unprocessed')
                        elif method=='DevDepot_updateObjects':
                            E.SubElement(E.SubElement(root,Q+'snapshots'),Q+'data').text=snap
                        else:raise AssertionError('Unexpected RPC '+str(method))
                        response=b'\xef\xbb\xbf'+E.tostring(root,encoding='utf-8')
                        inner.request.sendall(('HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n'%len(response)).encode()+response+END);inner.request.recv(1)
                    except BaseException as exc:errors.append(exc)
            class Server(socketserver.ThreadingTCPServer):allow_reuse_address=True;daemon_threads=True
            with Server(('127.0.0.1',0),Handler) as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    url='tcp://127.0.0.1:'+str(server.server_address[1])+'/test'
                    data=api.unseal(prepared/'prepared.json');data['binding']['url']=url;api.seal(prepared/'prepared.json',data)
                    config=dict(url=url,repository='test',platform='8.5.1.1529',username='test',password_env='CRS_COMMIT_SYNTHETIC',
                                state_directory=str(work/'state'),oscript=OSCRIPT,python=sys.executable,module_path=str(ROOT/'oscript_modules'),operation_timeout_seconds=120)
                    def run(action,params):
                        try:return cli.backend(dict(schema=1,action=action,profile='lab',params=params),config)
                        except cli.CLIError as exc:raise AssertionError((exc.code,calls,errors)) from exc
                    with mock.patch.dict(os.environ,CRS_COMMIT_SYNTHETIC=''):
                        plan=api.make_plan(dict(prepared_directory=str(prepared),comment='Synthetic commit'),config,run)
                        self.assertTrue(plan['plan']['ready'],plan)
                        args=dict(plan_file=plan['plan_file'],approved_plan_sha256=plan['plan_sha256'],execute=True)
                        if fault=='lost_reply':
                            with self.assertRaises(api.CommitError) as raised:api.execute(args,config,run)
                            self.assertEqual(raised.exception.code,'outcome_unknown')
                            with self.assertRaises(api.CommitError):api.execute(args,config,run)
                        else:
                            result=api.execute(args,config,run)
                            self.assertTrue(result['committed'],result)
                            self.assertEqual(result['version'],2)
                            self.assertEqual(result['readback_verified'],fault!='readback',result)
                            self.assertEqual(result['fully_completed'],fault!='readback',result)
                            self.assertTrue(api.execute(args,config,run)['already_executed'])
                        status=api.status(dict(plan_file=plan['plan_file'],plan_sha256=plan['plan_sha256']),config,run)
                        self.assertTrue(status['attempted']);self.assertIn('journal',status)
                finally:server.shutdown();thread.join()
            self.assertEqual(errors,[])
            self.assertEqual(state['commits'],1)
            self.assertEqual(state['captures'],0 if owned else 1)
            self.assertEqual(state['releases'],0 if owned or fault else 1)
            self.assertEqual(state['captured'],bool(owned or fault))
            return calls

    def test_capture_commit_native_readback_release_and_idempotent_result(self):self.run_case()
    def test_preexisting_own_capture_is_preserved(self):self.run_case(owned=True)
    def test_lost_put_reply_retains_capture_and_never_resends(self):self.run_case('lost_reply')
    def test_readback_mismatch_reports_committed_but_incomplete(self):self.run_case('readback')


if __name__=='__main__':unittest.main()
