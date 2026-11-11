"""Common protocol dependencies and conservative preservation of opaque links."""
import sys,unittest,json,zlib,base64,types
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_graph as graph
import compiled_dependencies as deps
import native_metadata as s
import native_object_reader

Q='{http://v8.1c.ru/8.3/MDClasses}'
ROOT='11111111-1111-4111-8111-111111111111'
OID='22222222-2222-4222-8222-222222222222'
OTHER='33333333-3333-4333-8333-333333333333'
TYPE='44444444-4444-4444-8444-444444444444'
OPAQUE='55555555-5555-4555-8555-555555555555'


def index(reference=False):
    root=E.Element(Q+'Configuration',uuid=ROOT)
    node=E.Element(Q+'SessionParameter',uuid=OID,attrib={'xmlns:cfg':'http://v8.1c.ru/8.1/data/enterprise/current-config'})
    if reference:
        props=E.SubElement(node,Q+'Properties');typ=E.SubElement(props,Q+'Type')
        E.SubElement(typ,'{http://v8.1c.ru/8.1/data/core}Type').text='cfg:EnumRef.Other'
    enum=E.Element(Q+'Enum',uuid=OTHER);info=E.SubElement(enum,Q+'InternalInfo')
    declaration=E.SubElement(info,graph.XR+'GeneratedType',name='EnumRef.Other')
    E.SubElement(declaration,graph.XR+'TypeId').text=TYPE
    def body(oid,name,more=()):
        a=s.atom
        return s.native_body_bytes([[a(0),[a(3),[a(1),a(0),a(oid)],a(name,True)],*more]])
    records={ROOT:dict(id=ROOT,kind='Configuration',parent_id=s.ZERO,name='Cfg',node=root),
             OID:dict(id=OID,kind='SessionParameter',parent_id=ROOT,name='Value',node=node),
             OTHER:dict(id=OTHER,kind='Enum',parent_id=ROOT,name='Other',node=enum)}
    image={OID:body(OID,'Value',([s.atom('Pattern',True),[s.atom('#',True),s.atom(TYPE)]],) if reference else ()),OTHER:body(OTHER,'Other',(s.atom(TYPE),))}
    return graph.TypeIndex(records,image),E.tostring(node,encoding='unicode')


class CompiledDependenciesTests(unittest.TestCase):
    def test_native_catalog_self_reference_never_creates_a_self_dependency(self):
        saved=json.loads(Path(__file__).with_name('fixtures').joinpath('compiled_attribute_types.json').read_text(encoding='utf-8'))
        case=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))['stages']['self-reference']
        metadata=s.Parser(case['metadata']).documents()[0];oid=s.val(metadata[1]);parent=s.val(metadata[3])
        node=E.fromstring(case['owner_xml'])[0];record=dict(id=oid,kind='Catalog',node=node)
        body=s.Parser(case['owner']).documents()
        generated=graph.generated(record);features=graph.features(record)
        children=native_object_reader.stored_collections(body,'Catalog')
        facts=types.SimpleNamespace(features=features,generated=generated,children=children,parent_id=parent)
        name='cfg:CatalogRef.CRSAPI_TestCatalog'
        reference=next(entry.findtext(graph.XR+'TypeId') for entry in node.iter(graph.XR+'GeneratedType')
                       if entry.get('name')==name[4:])
        current=types.SimpleNamespace(inventory={oid:record,parent:dict(kind='Configuration')},
            feature_owners={key:oid for key in features},facts=lambda _:facts,
            owner_for_generated=lambda value:oid if value in generated else None,
            reference=lambda value:(reference,oid) if value==name else self.fail('Unknown type'),
            resolve_required=lambda values:{value:reference for value in values},
            object_ids_required=lambda values:{oid} if values else set())
        result=deps.references(current,record,case['owner'].encode(),{oid:case['owner'].encode()},case['owner_xml'])
        self.assertEqual(result,{parent:1,**{child:1 for group in children.values() for child in group}})
        self.assertNotIn(oid,result)

    def test_type_dependency_and_parent_are_built_without_a_class_profile(self):
        current,xml=index(True)
        result=deps.reconcile(dict(_compiled_types=current),dict(object_id=OID,object_xml=xml),current.image[OID],current.image)
        self.assertEqual(s.metadata_relations(result),{ROOT:1,OTHER:0})

    def test_removal_replaces_only_proven_dependencies_and_keeps_opaque_links(self):
        source,_=index(True);current,xml=index(False)
        result=deps.reconcile(dict(_compiled_types=current,_source_types=source),dict(object_id=OID,object_xml=xml),current.image[OID],current.image,
                              {ROOT:1,OTHER:0,OPAQUE:1},source.image[OID],source.image)
        self.assertEqual(s.metadata_relations(result),{ROOT:1,OPAQUE:1})

    def test_source_type_namespace_survives_elementtree_namespace_loss(self):
        source,xml=index(True);current,final_xml=index(False)
        source.inventory[OID]['xml']=xml.replace('xmlns:cfg=','xmlns:project=').replace('cfg:EnumRef','project:EnumRef')
        source.inventory[OID]['node'].attrib.pop('xmlns:cfg')
        result=deps.reconcile(dict(_compiled_types=current,_source_types=source),
            dict(object_id=OID,object_xml=final_xml),current.image[OID],current.image,
            {ROOT:1,OTHER:0,OPAQUE:1},source.image[OID],source.image)
        self.assertEqual(s.metadata_relations(result),{ROOT:1,OPAQUE:1})

    def test_generated_id_of_a_surviving_owner_cannot_change(self):
        source,_=index();record=source.inventory[OTHER]
        changed=dict(record,node=E.fromstring(E.tostring(record['node'])))
        changed['node'].find('.//'+graph.XR+'TypeId').text=OPAQUE
        with self.assertRaisesRegex(ValueError,'surviving metadata object'):deps.validate_surviving_types(record,changed)


if __name__=='__main__':unittest.main()
