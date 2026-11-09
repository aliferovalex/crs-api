"""Compiled module payloads and repository stream-version reconciliation."""
import base64,copy,sys,unittest,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import native_content as n
import native_metadata as s
import serialization_context as c
OID='11111111-1111-4111-8111-111111111111'
VERSION='22222222-2222-4222-8222-222222222222'
class CompiledStreamsTests(unittest.TestCase):
 def frame(self,streams):
  a=s.atom;m=[a(0) for _ in range(17)];m[11]=[a(len(streams))]+[v for k in streams for v in (a(k,True),a(VERSION))]
  m[1]=a(OID);m[13]=[a(0)]
  return [m,[a(0)],[a(0)]]
 def run_change(self,before,after,previous,names):
  docs=self.frame(previous)
  return n.compiled_stream_changes(docs,copy.deepcopy(docs),b'body',OID,before,after,set(names))
 def test_add_module_preserves_other_streams_without_resending_them(self):
  old=OID+'.3';new=OID+'.0';before={old:b'manager'};after=dict(before,**{new:b'object'})
  result=self.run_change(before,after,[old],[old,new]);rows={r['name']:r for r in result.externals}
  self.assertEqual(rows[old]['action'],0);self.assertEqual(rows[new]['action'],1)
  self.assertEqual(bytes.fromhex(rows[old]['version']),uuid.UUID(VERSION).bytes_le+bytes(4))
  self.assertEqual([(k,s.inflate(v)) for k,v in result.streams],[(new,b'object')])
  self.assertEqual(len(result.docs[0][11]),5)
 def test_edit_clear_and_remove_modules(self):
  name=OID+'.0'
  for final in (b'edited',b''):
   with self.subTest(final=final):
    result=self.run_change({name:b'old'},{name:final},[name],[name])
    self.assertEqual(s.inflate(result.streams[0][1]),final)
    self.assertEqual(result.externals[0]['action'],1)
  result=self.run_change({name:b'old'},{},[name],[name])
  self.assertEqual(result.streams,[]);self.assertEqual(result.externals,[]);self.assertEqual(s.val(result.docs[0][11][0]),'0')
 def test_missing_or_unrequested_source_changes_are_rejected(self):
  name=OID+'.0'
  for before,after,previous,names in [({}, {name:b'new'},[name],[name]),({name:b'old'},{name:b'new'},[name],[]),({name:b'old'},{name:b'old'},[],[name])]:
   with self.subTest(before=before),self.assertRaises(ValueError):self.run_change(before,after,previous,names)
if __name__=='__main__':unittest.main()
