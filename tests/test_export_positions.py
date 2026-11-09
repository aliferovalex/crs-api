"""Repository ordinals are explicit changes, independent of file contents."""
import base64,copy,json,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import configuration_export as export
import metadata_context
import native_metadata as s
class ExportPositionTests(unittest.TestCase):
 def test_positions_follow_owner_xml_per_class_not_file_sort(self):
  root=E.fromstring('<Configuration xmlns="'+export.Q[1:-1]+'"><ChildObjects><Language>Russian</Language><Catalog>B</Catalog><Document>A</Document><Catalog>A</Catalog></ChildObjects></Configuration>')
  objects={'root':dict(node=root,parent_id=s.ZERO,kind='Configuration',name='Cfg')}
  for oid,kind,name in [('a','Catalog','A'),('b','Catalog','B'),('d','Document','A'),('l','Language','Russian')]:objects[oid]=dict(node=E.Element(kind),parent_id='root',kind=kind,name=name)
  self.assertEqual(export.positions(objects),{'l':0,'b':0,'d':0,'a':1})
 def test_position_mismatch_is_planned_even_with_identical_xml(self):
  fixture=Path(__file__).with_name('fixtures')/'ibcmd_document';request=json.loads((fixture/'request.json').read_text(encoding='utf-8'))['request']
  objects=metadata_context.context_objects(request['context']);_,_,inventory,_=export.inventory(fixture/'baseline')
  oid=next(key for key,row in inventory.items() if row['kind']=='Catalog');objects[oid][0][10]=s.atom(99)
  context=base64.b64encode(s.storage([s.text_bytes(row) for row in objects.values()],s.text_bytes([[s.atom(0)]]))).decode()
  plan=export.plan(dict(directory=str(fixture/'baseline'),baseline_directory=str(fixture/'baseline'),context=context))
  self.assertEqual(len(plan['operations']),1);op=plan['operations'][0]
  self.assertEqual(op['object_id'],oid);self.assertTrue(op['position_changed']);self.assertEqual(op['position'],0);self.assertEqual(op['changed_files'],[])
if __name__=='__main__':unittest.main()
