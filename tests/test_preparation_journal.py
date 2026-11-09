"""Durable write-ahead phases, ownership, immutable packets and restart claims."""
import base64,copy,json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/Сериализация'))
import preparation_journal as journal

USER='11111111-1111-4111-8111-111111111111'
REPO='22222222-2222-4222-8222-222222222222'
ROOT='33333333-3333-4333-8333-333333333333'
VER='44444444-4444-4444-8444-444444444444'
ONE=dict(pid=100,born=1);TWO=dict(pid=200,born=2)

def info(repo=REPO):
 return '<call_return xmlns="http://v8.1c.ru/8.2/crs"><info><info><depotID value="'+repo+'"/></info></info></call_return>'

class JournalTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.cache=Path(self.temp.name)/'cache'
  self.state=dict(repository_id=REPO,root_id=ROOT,repository_version=VER,platform='8.5.1.1529')
  self.snapshot=dict(state='Подготовка',captures=[],order=[],created=[],version=VER,recovery=None)
  patch=mock.patch.object(journal.repository_cache.Cache,'load',return_value=(self.state,{},self.cache/'base.cf'));patch.start();self.addCleanup(patch.stop)
 def call(self,request,owner=ONE):
  with mock.patch.object(journal,'process_identity',return_value=owner):return journal.run(request)
 def create(self):return self.call(dict(mode='create',cache_directory=str(self.cache),user_id=USER,snapshot=copy.deepcopy(self.snapshot)))
 def save(self,result,phase,packet=None):
  snap=copy.deepcopy(result['snapshot']);snap['state']=phase
  req=dict(mode='save',directory=result['directory'],revision=result['revision'],snapshot=snap)
  if packet:req['packet']=base64.b64encode(packet).decode()
  return self.call(req)
 def claim(self,result,owner=TWO,**extra):
  request=dict(mode='claim',directory=result['directory'],user_id=USER,repository_info=info(),platform='8.5.1.1529');request.update(extra)
  return self.call(request,owner)
 def test_ready_restart_keeps_packet_but_cannot_resume_sending(self):
  result=self.save(self.create(),'Готово',b'packet')
  claimed=self.claim(result)
  self.assertEqual(claimed['snapshot']['state'],'Восстановлено')
  self.assertEqual(base64.b64decode(claimed['packet']),b'packet')
  self.assertEqual(claimed['revision'],result['revision']+1)
  raw=(Path(result['directory'])/'state.json').read_text(encoding='utf-8')
  self.assertNotIn('password',raw);self.assertNotIn('auth',raw)
 def test_inflight_restart_is_uncertain_and_live_owner_cannot_be_claimed(self):
  result=self.save(self.create(),'Отправка',b'packet')
  with self.assertRaisesRegex(ValueError,'still running'):self.claim(result,ONE)
  self.assertEqual(self.claim(result)['snapshot']['state'],'ИсходНеизвестен')
 def test_stale_revision_and_old_owner_cannot_write(self):
  result=self.create();updated=self.save(result,'Готово')
  before=(Path(result['directory'])/'state.json').read_bytes()
  with self.assertRaisesRegex(ValueError,'changed'):self.save(result,'Отправка')
  self.assertEqual((Path(result['directory'])/'state.json').read_bytes(),before)
  claimed=self.claim(updated)
  with self.assertRaisesRegex(ValueError,'owner'):self.save(claimed,'Отправка')
 def test_foreign_repository_platform_and_user_do_not_claim(self):
  result=self.create();path=Path(result['directory'])/'state.json';before=path.read_bytes()
  for extra in (dict(user_id=ROOT),dict(repository_info=info(ROOT)),dict(platform='8.5.4.1878')):
   with self.subTest(extra=extra),self.assertRaisesRegex(ValueError,'another'):self.claim(result,**extra)
   self.assertEqual(path.read_bytes(),before)
 def test_packet_is_immutable_and_corruption_is_rejected(self):
  result=self.save(self.create(),'Готово',b'packet')
  with self.assertRaisesRegex(ValueError,'immutable'):self.save(result,'Готово',b'other')
  result=self.save(result,'Готово',b'packet')
  (Path(result['directory'])/'packet.bin').write_bytes(b'corrupt')
  with self.assertRaisesRegex(ValueError,'checksum'):self.claim(result)
 def test_state_checksum_and_dead_writer_lock(self):
  result=self.create();folder=Path(result['directory'])
  (folder/'write.lock').write_text(json.dumps(ONE))
  claimed=self.claim(result);self.assertTrue((folder/'write.lock').exists())
  data=json.loads((folder/'state.json').read_text(encoding='utf-8'));data['data']['snapshot']['state']='Отправка'
  (folder/'state.json').write_text(json.dumps(data),encoding='utf-8')
  with self.assertRaisesRegex(ValueError,'checksum'):self.claim(claimed)
 def test_capture_attempt_and_verified_timestamp_survive_restart(self):
  self.snapshot['captures']=[dict(id=ROOT,new=True,date='',version=1)];self.snapshot['order']=[ROOT]
  result=self.create();self.assertEqual(self.claim(result)['snapshot']['captures'][0]['date_token'],'@')
 def test_iso_capture_token_is_not_a_json_date_on_the_wire(self):
  token='2026-11-05T12:46:36'
  self.snapshot['captures']=[dict(id=ROOT,new=True,date=token,version=1)];self.snapshot['order']=[ROOT]
  result=self.create();claimed=self.claim(result)
  self.assertEqual(claimed['snapshot']['captures'][0]['date_token'],'@'+token)
  self.assertNotIn('date',claimed['snapshot']['captures'][0])
  stored=journal.read(Path(result['directory']))
  self.assertEqual(stored['snapshot']['captures'][0]['date'],token)
 def test_owner_process_identity_is_stable(self):
  me=journal.process_identity(os.getpid());self.assertIsNotNone(me);self.assertTrue(journal.alive(me))
 def test_live_writer_lock_excludes_another_writer(self):
  result=self.create();folder=Path(result['directory'])
  with journal.locked(folder):
   with self.assertRaisesRegex(ValueError,'being written'):self.claim(result)
  self.assertEqual(self.claim(result)['snapshot']['state'],'Восстановлено')
 def test_writer_process_death_releases_kernel_lock(self):
  result=self.create();folder=Path(result['directory']);marker=folder/'writer-ready'
  source=Path(journal.__file__).parent
  code="import sys,time;sys.path.insert(0,sys.argv[1]);from pathlib import Path;import preparation_journal as j\nwith j.locked(Path(sys.argv[2])):\n Path(sys.argv[3]).write_text('ready');time.sleep(30)"
  child=subprocess.Popen([sys.executable,'-I','-S','-c',code,str(source),str(folder),str(marker)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
  try:
   until=time.monotonic()+10
   while not marker.exists():
    if child.poll() is not None:self.fail(child.stderr.read().decode(errors='replace'))
    if time.monotonic()>until:self.fail('Writer did not acquire the lock')
    time.sleep(.02)
   with self.assertRaisesRegex(ValueError,'being written'):self.claim(result)
   child.kill();child.wait(timeout=10)
   self.assertEqual(self.claim(result)['snapshot']['state'],'Восстановлено')
  finally:
   if child.poll() is None:child.kill();child.wait(timeout=10)
   child.stderr.close()

if __name__=='__main__':unittest.main()
