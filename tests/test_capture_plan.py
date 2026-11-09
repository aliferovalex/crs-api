"""Pre-compilation capture plans contain existing objects, never new UUIDs."""
import json,re,shutil,sys,tempfile,unittest,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/Сериализация'))
import configuration_export as export

class CapturePlanTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.work=Path(self.temp.name);fixture=Path(__file__).parent/'fixtures/ibcmd_document'
  self.source=self.work/'source';self.target=self.work/'target'
  shutil.copytree(fixture/'baseline',self.source);shutil.copytree(self.source,self.target)
  self.context=json.loads((fixture/'request.json').read_text(encoding='utf-8'))['request']['context']
 def plan(self):return export.plan(dict(directory=str(self.target),baseline_directory=str(self.source),context=self.context))
 def test_no_change_needs_no_captures(self):
  self.assertEqual(self.plan()['capture_ids'],[])
 def test_changed_existing_object_is_captured_before_compilation(self):
  path=next((self.target/'Catalogs').glob('*.xml'));text=path.read_text(encoding='utf-8-sig')
  text,count=re.subn(r'<Comment(?:\s*/>|>.*?</Comment>)','<Comment>Local capture plan</Comment>',text,count=1,flags=re.S)
  self.assertEqual(count,1);path.write_text(text,encoding='utf-8')
  oid=export.inventory(self.target)[2];owner=next(k for k,v in oid.items() if v['path']==path.relative_to(self.target).as_posix())
  self.assertEqual(self.plan()['capture_ids'],[owner])
 def test_creation_and_deletion_capture_parent_and_deleted_object_only(self):
  _,_,records,root=export.inventory(self.source);row=next(v for v in records.values() if v['kind']=='Constant')
  text=(self.target/row['path']).read_text(encoding='utf-8-sig');newname='CapturePlanNew';text=text.replace(row['name'],newname)
  for oid in set(re.findall(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',text)):text=text.replace(oid,str(uuid.uuid4()))
  (self.target/row['path']).unlink();(self.target/'Constants'/ (newname+'.xml')).write_text(text,encoding='utf-8')
  path=self.target/'Configuration.xml';text=path.read_text(encoding='utf-8-sig');text=text.replace('<Constant>'+row['name']+'</Constant>','<Constant>'+newname+'</Constant>');path.write_text(text,encoding='utf-8')
  plan=self.plan();self.assertEqual(plan['capture_ids'],sorted([row['id'],root['id']]))
  self.assertTrue(set(plan['capture_ids']).isdisjoint(plan['new_ids']))

if __name__=='__main__':unittest.main()
