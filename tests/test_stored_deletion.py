"""Stored-child deletion planning and complete final repository graphs."""
import base64,copy,json,shutil,sys,tempfile,unittest,uuid
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import configuration_commit as commit
import configuration_export as export
import metadata_context
import metadata_structure
import native_metadata as s
FORM='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
VERSION='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
class StoredDeletionTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.work=Path(self.temp.name)
  fixture=Path(__file__).with_name('fixtures')/'ibcmd_document';self.base=self.work/'base';self.target=self.work/'target';shutil.copytree(fixture/'baseline',self.base)
  request=json.loads((fixture/'request.json').read_text(encoding='utf-8'))['request'];self.objects=metadata_context.context_objects(request['context'])
  _,_,records,_=export.inventory(self.base);owner=next(v for v in records.values() if v['kind']=='Catalog');self.owner=owner['id']
  cls=next(c['item_class_id'] for c in metadata_structure.profile('Catalog')['collections'] if c['xml_name']=='Form')
  docs=copy.deepcopy(self.objects[self.owner]);m=docs[0];m[1]=s.atom(FORM);m[2]=s.atom(cls);m[3]=s.atom(self.owner);m[9]=s.atom('DeletedForm',True);m[11]=[s.atom(1),s.atom(FORM+'.0',True),s.atom(VERSION)];m[12]=[s.atom(0)];m[13]=[s.atom(0)];m[14]=[s.atom(1),s.atom(self.owner),s.atom(1)]
  self.objects[FORM]=docs;self.objects[self.owner][0][12]=[s.atom(1),[s.atom(cls),s.atom(1),s.atom(FORM)]]
  path=self.base/owner['path'];tree=E.parse(path);E.SubElement(tree.getroot()[0].find(export.Q+'ChildObjects'),export.Q+'Form').text='DeletedForm';tree.write(path,encoding='utf-8')
  self.descriptor=Path(owner['path']).with_suffix('')/'Forms/DeletedForm.xml';p=self.base/self.descriptor;p.parent.mkdir(parents=True)
  p.write_text('<MetaDataObject xmlns="'+export.Q[1:-1]+'" version="2.21"><Form uuid="'+FORM+'"><Properties><Name>DeletedForm</Name></Properties></Form></MetaDataObject>',encoding='utf-8')
  interface=p.with_suffix('')/'Ext/Form.xml';interface.parent.mkdir(parents=True);interface.write_text('<Form/>',encoding='utf-8')
  path=self.base/'ConfigDumpInfo.xml';tree=E.parse(path)
  for key in (FORM,FORM+'.0'):E.SubElement(tree.getroot()[0],export.D+'Metadata',id=key,configVersion=uuid.UUID(VERSION).bytes_le.hex()+'00000000')
  # The body and stream versions share the same clean-room UUID.
  self.objects[FORM][0][7]=self.objects[FORM][0][8]=s.atom(VERSION)
  tree.write(path,encoding='utf-8');shutil.copytree(self.base,self.target)
  (self.target/self.descriptor).unlink();(self.target/self.descriptor.with_suffix('')/'Ext/Form.xml').unlink()
  path=self.target/owner['path'];tree=E.parse(path);children=tree.getroot()[0].find(export.Q+'ChildObjects');children.remove(next(n for n in children if n.tag==export.Q+'Form'));tree.write(path,encoding='utf-8')
  context=base64.b64encode(s.storage([s.text_bytes(row) for row in self.objects.values()],s.text_bytes([[s.atom(0)]]))).decode()
  self.request=dict(request,context=context,directory=str(self.target),baseline_directory=str(self.base))
 def test_deleted_descriptor_is_not_read_from_target_and_both_snapshots_are_requested(self):
  plan,changes=commit.prepare(self.request)
  self.assertEqual(plan['removed_ids'],[FORM]);self.assertEqual(set(plan['snapshot_ids']),set(self.objects))
  self.assertEqual([v['object_id'] for v in changes],[self.owner]);self.assertIn(FORM,changes[0]['_removed_children'])
 def test_final_graph_excludes_deleted_object_but_carries_source_relations(self):
  kept=copy.deepcopy(self.objects);kept.pop(FORM);kept[self.owner][0][12]=[s.atom(0)]
  graph=commit.final_graph(self.objects,kept,[self.owner],{FORM})
  self.assertEqual(int(s.val(graph[0][0])),len(kept));self.assertNotIn(FORM,[s.val(v) for v in graph[0][1::2]])
  existence={s.val(graph[4][i]):s.val(graph[4][i+1]) for i in range(1,len(graph[4]),2)}
  self.assertEqual(existence[FORM],'0');self.assertEqual(existence[self.owner],'1');self.assertEqual(s.val(graph[10]),'1')
  self.assertEqual(int(s.val(graph[11][0])),len(self.objects));self.assertNotIn(FORM,s.render(graph[5]))
if __name__=='__main__':unittest.main()
