"""One commit RPC for changes, creations, deletions and mixed configuration groups."""
import copy
import json
from pathlib import Path
import socketserver
import subprocess
import tempfile
import threading
import unittest
from xml.etree import ElementTree as E
from test_version_labels import OSCRIPT, ROOT, Q, END
import sys
sys.path.insert(0,str(ROOT/'src'/'Сериализация'))
import metadata_identifiers as ids

PARENT='11111111-1111-4111-8111-111111111111'
ITEM='22222222-2222-4222-8222-222222222222'
NEW='33333333-3333-4333-8333-333333333333'
REPO='44444444-4444-4444-8444-444444444444'
NEXT='55555555-5555-4555-8555-555555555555'
USER='66666666-6666-4666-8666-666666666666'
ZERO='00000000-0000-0000-0000-000000000000'


def row(oid,kind,name,parent,version=7,original='a',local=None):
    return dict(id=oid,class_id=ids.class_id(kind),name=name,parent_id=parent,owner_id=ZERO,
                pos=0,version=version,original=original*32+'00000000',local=(local or original)*32+'00000000')


def settings(mode,fault):
    parent=row(PARENT,'Configuration','Root',ZERO)
    child=row(ITEM,'Constant','Item',PARENT,original='c')
    updated=dict(parent,local='b'*32+'00000000')
    if mode=='change':
        source=row(ITEM,'CommonModule','Module',PARENT)
        sources=[source];expected=[dict(source,local='b'*32+'00000000')];target=ITEM
    elif mode=='create': sources=[parent];expected=[updated,row(ITEM,'Constant','NewItem',PARENT,0,'d')];target=ITEM
    elif mode=='delete': sources=[parent,child];expected=[updated];target=ITEM
    else: sources=[parent,child];expected=[updated,row(NEW,'Constant','NewItem',PARENT,0,'d')];target=PARENT
    errors={'capture':'захвачены','other_user':'другим пользователем','stale_source':'устарел',
            'collision':'уже существует','stale_repository':'Хранилище изменилось',
            'wrong_repository':'другого хранилища','hash':'описание помещённого',
            'position':'описание помещённого','name':'описание помещённого',
            'class':'описание помещённого','parent':'описание помещённого','owner':'описание помещённого',
            'old_version':'описание помещённого','mixed_versions':'разные версии','not_deleted':'Удаление объекта'}
    return dict(mode=mode,fault=fault,sources=sources,expected=expected,target_id=target,
                result_id=PARENT if mode=='delete' else target,repository_version=REPO,
                changed_ids=[PARENT],new_ids=[NEW],removed_ids=[ITEM],
                data='AgFTS2/0iI3BTqDV67a9oKcNAA==',error_contains=errors.get(fault,''))


def reply(): return E.Element(Q+'call_return')
def value(node,key,v): return E.SubElement(node,Q+key,value=str(v).lower() if isinstance(v,bool) else str(v))


@unittest.skipUnless(OSCRIPT and Path(OSCRIPT).is_file(),'OneScript unavailable')
class CommitExecutorTests(unittest.TestCase):
    def run_case(self,mode,fault='none'):
        config=settings(mode,fault);before=copy.deepcopy(config['sources']);after=copy.deepcopy(config['expected'])
        for r in after:r['version']=8
        if fault=='old_version':
            for r in after:r['version']=7
        if fault=='mixed_versions':after[-1]['version']=9
        for key,new in [('hash','e'*32+'00000000'),('position',9),('name','Unexpected'),
                        ('class',ids.class_id('Document')),('parent',NEW),('owner',USER)]:
            if fault==key:after[0][{'hash':'local','position':'pos','name':'name','class':'class_id','parent':'parent_id','owner':'owner_id'}[key]]=new
        if fault=='stale_source':before[0]['original']='e'*32+'00000000'
        if fault=='collision':before.append(copy.deepcopy(config['expected'][-1]))
        if fault=='not_deleted':after.append(copy.deepcopy(config['sources'][-1]))
        state=dict(commits=0,latest=0);calls=[];errors=[]
        class Handler(socketserver.BaseRequestHandler):
            def handle(inner):
                try:
                    inner.request.settimeout(10);inner.request.sendall(bytes.fromhex('53f5c61a7b'));raw=b''
                    while not raw.endswith(END):
                        part=inner.request.recv(65536)
                        if not part:raise AssertionError('Truncated request')
                        raw+=part
                    request=E.fromstring(raw.split(b'\r\n\r\n',1)[1][:-4]);method=request.get('name');calls.append(method);params=request.find(Q+'params');root=reply()
                    if method=='DevDepot_depotInfo':value(root,'ok',True)
                    elif method=='UserManager_depotUserByName':
                        user=E.SubElement(root,Q+'user');info=E.SubElement(user,Q+'info')
                        for key,v in dict(id=USER,name='test',password='synthetic',rights='3').items():value(info,key,v)
                        value(user,'online',False);value(user,'removed',False)
                    elif method=='DevDepot_latestVerID':
                        state['latest']+=1
                        v=NEXT if state['commits'] or fault=='stale_repository' and state['latest']>=3 else REPO
                        value(root,'verID',v)
                    elif method=='DevDepot_devObjectsStatistic':
                        rows=after if state['commits'] else before;group=E.SubElement(root,Q+'statMap')
                        for r in rows:
                            item=E.SubElement(group,Q+'value');value(item,'first',r['id']);info=E.SubElement(item,Q+'second')
                            value(info,'verNum',r['version']);value(info,'revised',fault!='capture')
                            value(info,'revisorID',ZERO if fault=='other_user' else USER);value(info,'reviseDate','2026-01-01T00:00:00')
                    elif method=='DevDepot_versionObjects':
                        number=int(params.find(Q+'verNum').get('value'));group=E.SubElement(root,Q+'objects')
                        for r in after if state['commits'] else before:
                            if r['version']!=number:continue
                            item=E.SubElement(group,Q+'value');value(item,'first',r['id']);info=E.SubElement(E.SubElement(item,Q+'second'),Q+'info')
                            identity=E.SubElement(info,Q+'_super');value(identity,'id',r['id']);value(identity,'classID',r['class_id'])
                            for key,field in [('name','name'),('pos','pos'),('verNum','version'),('selfVerNum','version'),('parentID','parent_id'),('ownerID','owner_id')]:value(info,key,r[field])
                            versions=E.SubElement(info,Q+'version');value(versions,'original',r['original']);value(versions,'local',r['local']);value(info,'removed',False)
                    elif method=='DevDepot_commitObjects':
                        state['commits']+=1
                        self.assertEqual(params.find(Q+'comment').text,'Unified & commit')
                        self.assertEqual(params.find(Q+'clientVerID').get('value'),REPO)
                        self.assertEqual(len(params.find(Q+'changes')),len(config['expected']))
                        if fault=='lost_reply':return
                        E.SubElement(root,Q+'exc');result=E.SubElement(root,Q+'result');E.SubElement(result,Q+'unprocessed')
                    else:raise AssertionError('Unexpected RPC '+str(method))
                    body=b'\xef\xbb\xbf'+E.tostring(root,encoding='utf-8')
                    inner.request.sendall(('HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n'%len(body)).encode()+body+END)
                    inner.request.recv(1)
                except BaseException as error:errors.append(error)
        class Server(socketserver.ThreadingTCPServer):allow_reuse_address=True;daemon_threads=True
        with tempfile.TemporaryDirectory() as directory,Server(('127.0.0.1',0),Handler) as server:
            path=Path(directory)/'input.json';path.write_text(json.dumps(config),encoding='utf-8')
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            try:result=subprocess.run([OSCRIPT,str(ROOT/'tests/check-commit-executor.os'),
                                       'tcp://127.0.0.1:'+str(server.server_address[1]),str(path)],cwd=ROOT,capture_output=True,timeout=35)
            finally:server.shutdown();worker.join()
        self.assertEqual(errors,[])
        self.assertEqual(result.returncode,0,(result.stdout+result.stderr).decode('utf-8',errors='replace'))
        preflight={'capture','other_user','stale_source','collision','stale_repository','wrong_repository'}
        self.assertEqual(state['commits'],0 if fault in preflight else 1)
        return calls

    def test_four_operations_have_one_commit_and_preserve_result_shape(self):
        for mode in ('change','create','delete','group'):
            with self.subTest(mode=mode):self.run_case(mode)

    def test_preconditions_prevent_commit(self):
        for fault in ('capture','other_user','stale_source','collision','stale_repository','wrong_repository'):
            with self.subTest(fault=fault):self.run_case('group',fault)

    def test_single_creation_also_checks_new_uuid_collision(self):self.run_case('create','collision')

    def test_confirmation_fields_apply_to_single_changes_too(self):
        for fault in ('hash','position','name','class','parent','owner','old_version'):
            with self.subTest(fault=fault):self.run_case('change',fault)

    def test_mixed_versions_and_incomplete_deletion_are_rejected(self):
        self.run_case('group','mixed_versions');self.run_case('delete','not_deleted')

    def test_lost_reply_never_retries(self):
        for mode in ('change','create','delete','group'):
            with self.subTest(mode=mode):self.run_case(mode,'lost_reply')
