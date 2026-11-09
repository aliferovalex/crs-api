"""Configuration collection identities and root graph reconciliation."""
import copy,sys,types,unittest,uuid,tempfile
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import native_metadata as s
import native_configuration_reader as reader
import compiled_metadata as compiled
import metadata_identifiers as ids
OID='11111111-1111-4111-8111-111111111111'
CHILD='22222222-2222-4222-8222-222222222222'
FEATURE='33333333-3333-4333-8333-333333333333'
OTHER='44444444-4444-4444-8444-444444444444'
CLASS=ids.class_id('Catalog')
def body(children=(CHILD,),version='1.0',feature=FEATURE,extra=None):
 a=s.atom;props=[a(0) for _ in range(77)];props[0]=a(76)
 props[1]=[a(0),[a(3),[a(1),a(0),a(feature)],a(0),a(0),a('Cfg',True),a(0),a(0),a(0),a(0)]]
 for i in reader.PROPERTY_SLOTS.values():props[i]=a(version if i==reader.PROPERTY_SLOTS['Version'] else '',True)
 root=[a(2),[a(OID)],a(1),[a(reader.ROOT_FEATURE_CLASS),[a(1),props]],[[a(CLASS),a(len(children))]+[a(v) for v in children]]]
 if extra:root.append(a(extra))
 return [root]
def frame():
 a=s.atom;m=[a(5),a(OID),a(reader.ROOT_CLASS),a(s.ZERO),a(s.ZERO),a(1),a(1),a(OTHER),a(OTHER),a('Cfg',True),a(0),[a(0)],[a(1),[a(CLASS),a(1),a(CHILD)]],[a(1),a(FEATURE)],[a(1),a(CHILD),a(1)],a('Cfg',True),a(0)]
 docs=[m,[a(0)],[a(0)]];child=copy.deepcopy(docs);child[0][1]=a(CHILD);child[0][2]=a(CLASS);child[0][3]=a(OID)
 return types.SimpleNamespace(saved=copy.deepcopy(docs),docs=docs,metadata=m),{OID:docs,CHILD:child}
class ConfigurationRootTests(unittest.TestCase):
 def content(self,target,removed=(),source=None):
  source=body() if source is None else source;f,objects=frame()
  req=dict(platform='8.5.1.1529',snapshots={OID:'snapshot'},originals={OID:uuid.UUID(OTHER).bytes_le.hex()+'00000000'})
  change=dict(kind='Configuration',object_id=OID,_removed_children={key:{} for key in removed})
  with mock.patch.object(compiled.serialization_context,'read',return_value=f):
   return compiled.content(req,change,objects,{OID:s.text_bytes(source)},{OID:s.text_bytes(target)})
 def test_scalar_root_edit_preserves_features_and_relationships(self):
  result=self.content(body(version='2.0'))
  self.assertEqual(s.metadata_relations(result.docs[0][14]),{CHILD:1})
  self.assertEqual([s.val(v) for v in result.docs[0][13][1:]],[FEATURE])
  self.assertEqual(result.body,s.text_bytes(body(version='2.0')))
 def test_delete_top_level_child_removes_only_its_relation(self):
  result=self.content(body(children=()),removed=[CHILD])
  self.assertEqual(s.metadata_relations(result.docs[0][14]),{})
  self.assertEqual(result.body,s.text_bytes(body(children=())))
 def test_inferred_class_handles_first_creation_and_last_deletion(self):
  cls='55555555-5555-4555-8555-555555555555'
  for create in (True,False):
   with self.subTest(create=create):
    source=body(children=() if create else (CHILD,));target=body(children=(CHILD,) if create else ())
    for native in (source,target):native[0][-1][0][0]=s.atom(cls)
    f,objects=frame();objects[CHILD][0][2]=s.atom(cls)
    if create:
     objects.pop(CHILD);f.metadata[12]=[s.atom(0)];f.metadata[14]=[s.atom(0)]
    else:f.metadata[12][1][0]=s.atom(cls)
    f.saved=copy.deepcopy(f.docs)
    row=dict(id=CHILD,kind='PaletteColor',parent_id=OID,_class_id=cls)
    node=E.Element(compiled.Q+'Configuration',uuid=OID)
    def index(groups):
     inventory={OID:dict(id=OID,kind='Configuration',node=node,parent_id=s.ZERO)}
     if groups:inventory[CHILD]=row
     return types.SimpleNamespace(inventory=inventory,owners={},feature_owners={FEATURE:OID},
       owner_for_generated=lambda _:None,resolve_required=lambda _: {},object_ids_required=lambda _:set(),
       facts=lambda _:types.SimpleNamespace(children=groups,features=(FEATURE,),generated=(),parent_id=s.ZERO))
    req=dict(platform='8.5.1.1529',snapshots={OID:'snapshot'},originals={OID:uuid.UUID(OTHER).bytes_le.hex()+'00000000'},
             _source_types=index({} if create else {cls:[CHILD]}),_compiled_types=index({cls:[CHILD]} if create else {}))
    change=dict(kind='Configuration',object_id=OID,object_xml=E.tostring(node,encoding='unicode'),
      _removed_children={} if create else {CHILD:row},_new_children={CHILD:row} if create else {})
    with mock.patch.object(compiled.serialization_context,'read',return_value=f):
     result=compiled.content(req,change,objects,{OID:s.text_bytes(source)},{OID:s.text_bytes(target)})
    self.assertEqual(s.metadata_relations(result.docs[0][14]),{CHILD:1} if create else {})
 def test_wrong_collections_features_or_other_references_fail(self):
  for target,removed in [(body(children=(OTHER,)),()),(body(feature=OTHER),()),(body(extra=OTHER),()),(body(children=()),())]:
   with self.subTest(removed=removed),self.assertRaises(ValueError):self.content(target,removed)
 def test_schema_collections_validate_counts_duplicate_classes_and_uuids(self):
  self.assertEqual(reader.stored_collections(body(),OID,'8.5.1.1529')[CLASS],[CHILD])
  bad=body();bad[0][-1][0][1]=s.atom(2)
  duplicate=body();duplicate[0][-1].append(copy.deepcopy(duplicate[0][-1][0]))
  twice=body(children=(CHILD,CHILD))
  for data in (bad,duplicate,twice):
   with self.assertRaises(ValueError):reader.stored_collections(data,OID,'8.5.1.1529')
 def test_root_xml_property_admission_is_delegated_to_compiler(self):
  original='<MetaDataObject xmlns="'+compiled.Q[1:-1]+'" version="2.21"><Configuration uuid="'+OID+'"><Properties><Name>Cfg</Name><Comment/><Version>1.0</Version><DefaultLanguage>Language.Russian</DefaultLanguage></Properties><ChildObjects><Catalog>Removed</Catalog></ChildObjects></Configuration></MetaDataObject>'
  with tempfile.TemporaryDirectory() as temp:
   baseline=Path(temp);(baseline/'Configuration.xml').write_text(original,encoding='utf-8')
   final=original.replace('<Comment/>','<Comment>Changed</Comment>').replace('<Version>1.0</Version>','<Version>2.0</Version>').replace('<Catalog>Removed</Catalog>','')
   change=dict(kind='Configuration',object_xml=final,_removed_children={CHILD:dict(kind='Catalog',name='Removed')})
   compiled.validate_xml(change,baseline,baseline,Path('Configuration.xml'))
   compiled.validate_xml(dict(change,object_xml=final.replace('Language.Russian','Language.Other')),baseline,baseline,Path('Configuration.xml'))

 def test_zero_parent_is_reserved_for_configuration_class(self):
  f,objects=frame();compiled.validate_graph(f,OID,objects)
  f.metadata[2]=s.atom(CLASS)
  with self.assertRaisesRegex(ValueError,'owner relation'):compiled.validate_graph(f,OID,objects)
if __name__=='__main__':unittest.main()
