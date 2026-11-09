"""Common creation metadata for externally compiled owner definitions."""
import base64,copy,json,sys,types,unittest
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_creation as creation
import native_metadata as s
import metadata_structure
import native_form_profiles
import native_configuration_reader as root_reader
OID='11111111-1111-4111-8111-111111111111'
PARENT='22222222-2222-4222-8222-222222222222'
FEATURE='33333333-3333-4333-8333-333333333333'
UNKNOWN='55555555-5555-4555-8555-555555555555'
def record(kind,oid,name,parent,features=()):
 q='{http://v8.1c.ru/8.3/MDClasses}';node=E.Element(q+kind,uuid=oid)
 children=E.SubElement(node,q+'ChildObjects')
 for feature in features:E.SubElement(children,q+'Attribute',uuid=feature)
 return dict(id=oid,kind=kind,name=name,parent_id=parent,node=node)

def parent_body(cls,children):
 a=s.atom;props=[a(0) for _ in range(77)];props[0]=a(76)
 props[1]=[a(0),[a(3),[a(1),a(0),a(UNKNOWN)],a('Cfg',True),[a(0)],a('',True),a(0),a(0),a(s.ZERO),a(0)]]
 for slot in root_reader.PROPERTY_SLOTS.values():props[slot]=a('',True)
 return s.text_bytes([[a(2),[a(PARENT)],a(1),[a(root_reader.ROOT_FEATURE_CLASS),[a(1),props]],[[a(cls),a(len(children))]+[a(v) for v in children]]]])
class CompiledCreationTests(unittest.TestCase):
 def setUp(self):
  self.fixtures=json.loads(Path(__file__).with_name('fixtures').joinpath('compiled_owners.json').read_text(encoding='utf-8'))
 def allocate(self,kind='Catalog',stream=None,children=(OID,),objects=None):
  cls=metadata_structure.profile(kind)['class_id'];raw=self.fixtures[kind]['before'].encode()
  image={OID:raw,PARENT:parent_body(cls,children)}
  if stream:image[OID+stream]=b'compiled module container'
  self.change=dict(kind=kind,object_id=OID,_record=record(kind,OID,'TestDocument',PARENT,(FEATURE,)),object_xml='<MetaDataObject/>')
  self.request=dict(platform='8.5.1.1529')
  parent=[[s.atom(0),s.atom(PARENT),s.atom(root_reader.ROOT_CLASS)],[s.atom(0)],[s.atom(0)]]
  return creation.allocate(self.request,self.change,objects or {PARENT:parent},image,parent,{OID:self.change['_record'],PARENT:record('Configuration',PARENT,'Cfg',s.ZERO)})
 def test_four_owner_profiles_share_the_repository_metadata_constructor(self):
  for kind in ('Catalog','Document','DataProcessor','Report'):
   with self.subTest(kind=kind):
    entry=self.allocate(kind);m=entry.docs[0]
    self.assertEqual(s.val(m[1]),OID);self.assertEqual(s.val(m[3]),PARENT)
    self.assertEqual(s.val(m[7]),s.val(m[8]));self.assertEqual(len(base64.b64decode(s.val(m[8]))),20)
    self.assertEqual({s.val(v) for v in m[13][1:]},{FEATURE})
    self.assertEqual(s.metadata_relations(m[14]),{PARENT:1})
    self.assertEqual(entry.body,self.fixtures[kind]['before'].encode())
    self.assertEqual(s.val(m[15]),metadata_structure.profile(kind)['class_id']+'.TestDocument')
 def test_new_modules_have_real_payloads_and_action_one(self):
  entry=self.allocate(stream='.0')
  self.assertEqual([(k,s.inflate(v)) for k,v in entry.streams],[(OID+'.0',b'compiled module container')])
  self.assertEqual(entry.externals[0]['action'],1)
 def test_schema_classes_outside_four_owners_use_the_same_constructor(self):
  for kind in ('Constant','Enum','CommonModule','SessionParameter'):
   with self.subTest(kind=kind):
    cls=metadata_structure.profile(kind)['class_id'];a=s.atom
    item=record(kind,OID,'Generic',PARENT)
    raw=s.native_body_bytes([[a(0),[a(3),[a(1),a(0),a(OID)],a('Generic',True)]]])
    image={OID:raw,PARENT:parent_body(cls,(OID,))}
    parent=[[a(0),a(PARENT),a(root_reader.ROOT_CLASS)],[a(0)],[a(0)]]
    entry=creation.allocate(dict(platform='8.5.1.1529'),dict(kind=kind,object_id=OID,_record=item),{PARENT:parent},image,parent,{OID:item,PARENT:record('Configuration',PARENT,'Cfg',s.ZERO)})
    self.assertEqual(s.val(entry.docs[0][2]),cls);self.assertEqual(s.val(entry.docs[0][13][0]),'0')
    self.assertEqual(entry.body,raw)
 def test_parent_membership_is_required_and_all_compiled_stream_names_are_retained(self):
  with self.assertRaisesRegex(ValueError,'absent'):self.allocate(children=())
  entry=self.allocate(stream='.999');self.assertEqual(entry.streams[0][0],OID+'.999')
 def test_reference_checks_reject_unresolved_owner_dependencies(self):
  entry=self.allocate();reader=types.SimpleNamespace(targets=types.SimpleNamespace(targets=[types.SimpleNamespace(object_id=OID),types.SimpleNamespace(object_id=PARENT)]))
  with mock.patch.object(creation.metadata_type_references,'resolve',return_value={}),mock.patch.object(creation.native_references,'catalog',return_value=reader),mock.patch.object(creation.metadata_type_references,'object_ids',return_value={UNKNOWN}):
   with self.assertRaisesRegex(ValueError,'unresolved'):creation.finalize(self.request,self.change,entry)
 def form_entry(self,kind,missing_stream=False,wrong_parent=False):
  profile=native_form_profiles.owner_profiles()[kind]
  cls=next(row['item_class_id'] for row in metadata_structure.profile(kind)['collections'] if row['xml_name']=='Form')
  definition=profile['body_template'].replace(s.ZERO,OID,1).replace('""','"NewForm"',1).encode()
  parent_body=s.text_bytes([[s.atom(cls),s.atom(1),s.atom(OID)]])
  metadata=[s.atom(0) for _ in range(17)];metadata[1]=s.atom(PARENT)
  metadata[2]=s.atom(root_reader.ROOT_CLASS if wrong_parent else metadata_structure.profile(kind)['class_id'])
  metadata[15]=s.atom('Owner.',True)
  parent=[metadata,[s.atom(0)],[s.atom(0)]]
  image={OID:definition,PARENT:parent_body}
  if not missing_stream:image[OID+'.0']=profile['external_template'].encode()
  change=dict(kind=kind+'Form',object_id=OID,_record=record('Form',OID,'NewForm',PARENT),form_xml='<Form/>')
  return creation.allocate(dict(platform='8.5.1.1529'),change,{PARENT:parent},image,parent,{OID:change['_record'],PARENT:record(kind,PARENT,'Owner',s.ZERO)}),cls,image
 def test_four_managed_form_classes_use_compiled_interface_and_parent_collection(self):
  for kind in ('Catalog','Document','Report','DataProcessor'):
   with self.subTest(kind=kind):
    entry,cls,image=self.form_entry(kind);m=entry.docs[0]
    self.assertEqual(s.val(m[2]),cls);self.assertEqual(s.val(m[10]),'0')
    self.assertEqual(s.val(m[13][0]),'0');self.assertEqual(s.val(m[15]),'Owner.'+cls+'.NewForm')
    self.assertEqual(entry.body,image[OID]);self.assertEqual(s.inflate(entry.streams[0][1]),image[OID+'.0'])
    self.assertEqual(entry.externals[0]['action'],1)
 def test_form_requires_matching_owner_and_compiled_interface(self):
  with self.assertRaisesRegex(ValueError,'parent class'):self.form_entry('Catalog',wrong_parent=True)
  with self.assertRaisesRegex(ValueError,'no interface'):self.form_entry('Catalog',missing_stream=True)
if __name__=='__main__':unittest.main()
