"""Full metadata types, including mutually dependent new native definitions."""
import base64
import json
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as E
import test_final_native_references as cases
import test_owned_template_creation as owned
import configuration_batch as batch
import configuration_commit as commit
import inline_attribute_xml as attrs
import inline_object_xml as inline
import metadata_object_xml as metadata
import metadata_type_references as refs
import native_metadata as s
import native_references
import object_creation_serializer as creation
import type_description_xml as types

Q=metadata.Q
REFS={'cfg:CatalogRef.FreshCatalog':str(uuid.UUID(int=11)),
      'cfg:DocumentRef.FreshDocument':str(uuid.UUID(int=12))}


def type_node(names):
    node=E.Element(Q+'Type')
    for name in names:E.SubElement(node,types.Q+'Type').text=name
    return node


def attribute(children,names,name='Link'):
    node=E.SubElement(children,Q+'Attribute',uuid=str(uuid.uuid4()))
    props=E.SubElement(node,Q+'Properties');E.SubElement(props,Q+'Name').text=name
    props.append(type_node(names));return node


class MetadataTypeTests(unittest.TestCase):
    def test_new_command_resolves_forward_and_self_parameter_types_and_module(self):
        import inline_command_xml as commands
        import metadata_context
        helper=cases.FinalNativeReferenceTests();r,_,owners,_,_=helper.case();self.addCleanup(helper.doCleanups)
        file=Path(r['directory'])/'Documents/FreshDocument.xml';top=E.parse(file);cid=str(uuid.uuid4())
        node=E.SubElement(top.getroot()[0].find(Q+'ChildObjects'),Q+'Command',uuid=cid);props=E.SubElement(node,Q+'Properties');E.SubElement(props,Q+'Name').text='ForwardCommand'
        parameter=type_node(['cfg:CatalogRef.FreshCatalog','cfg:EnumRef.FreshEnum','cfg:DocumentRef.FreshDocument','xs:boolean']);parameter.tag=Q+'CommandParameterType';props.append(parameter)
        file.write_bytes(E.tostring(top.getroot(),encoding='utf-8'));module=file.with_suffix('')/'Commands/ForwardCommand/Ext/CommandModule.bsl';module.parent.mkdir(parents=True);module.write_text('// whole reference command module',encoding='utf-8')
        plan,_=commit.prepare(r);r.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
        result=commit.serialize(r);_,records=batch.read_packet(result['data']);records={entry.object_id:entry for entry in records};body=s.Parser(s.inflate(records[owners['Document']].body).decode('utf-8-sig')).documents()[0]
        rule=metadata.profiles.layout('Document')['command_collections']['Command'];pattern=commands.at(body[rule['slot']][2],rule['type_path']);expected=set()
        for kind,oid in owners.items():
            layout=metadata.profiles.layout(kind);categories=layout.get('generated_categories',('Object','Ref','Selection','List','Manager'));target=s.Parser(s.inflate(records[oid].body).decode('utf-8-sig')).documents()[0]
            expected.add(s.val(target[1][layout['generated_slots'][categories.index('Ref')*2]]))
        self.assertEqual(refs.type_ids(pattern),expected);self.assertIn('{"B"}',s.render(pattern))
        docs=s.Parser(records[owners['Document']].metadata.decode('utf-8-sig')).documents();relations=s.metadata_relations(docs[0][14])
        for kind in ('Catalog','Enum'):self.assertEqual(relations[owners[kind]],0)
        self.assertNotIn(owners['Document'],relations)
        self.assertIn(cid+'.2',dict(records[owners['Document']].externals));self.assertIn(b'// whole reference command module',s.inflate(dict(records[owners['Document']].externals)[cid+'.2']))

    def test_existing_reference_uses_version_checked_snapshot_or_storage(self):
        import test_metadata_references as original
        import metadata_identifiers
        original.ReferenceTests.setUpClass();request,storage=original.ReferenceTests().fixture()
        request=dict(request,platform='8.5.1.1529');reader=native_references.Catalog(request)
        identity=next(row for row in reader.targets.targets if row.class_id==metadata_identifiers.class_id('Enum'))
        xml=E.tostring(type_node(['cfg:EnumRef.'+identity.name]),encoding='unicode')
        resolved=refs.resolve(xml,request)
        self.assertEqual(resolved,refs.resolve(xml,dict(request,storage=base64.b64encode(storage).decode())))
        self.assertNotEqual(resolved['cfg:EnumRef.'+identity.name],identity.object_id)
        with self.assertRaisesRegex(ValueError,'snapshot is required'):refs.resolve(xml,dict(request,reference_snapshots={}))

    def test_complete_xml_matches_independently_compiled_native_bodies(self):
        data=json.loads(Path(__file__).with_name('fixtures').joinpath('metadata_reference_types_851.json').read_text(encoding='utf-8'))
        for case in data['cases']:
            with self.subTest(kind=case['kind']):
                raw=metadata.create(case['xml'],data['platform'],case['kind'],type_references=data['references'])[2]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))

    def test_compound_reference_and_scalar_patterns_roundtrip(self):
        node=type_node(['cfg:DocumentRef.FreshDocument','xs:boolean','cfg:CatalogRef.FreshCatalog'])
        pattern=types.read_metadata(node,REFS)
        self.assertEqual([s.val(arm[0]) for arm in pattern[1:]],['B','#','#'])
        self.assertEqual(s.render(types.read_metadata(types.export_metadata(pattern,Q+'Type',REFS),REFS)),s.render(pattern))
        top=E.Element(Q+'ChildObjects');attr=attribute(top,['xs:boolean','cfg:CatalogRef.FreshCatalog'])
        _,_,entry=attrs.attribute_xml(attr,type_references=REFS)
        self.assertEqual(s.render(entry[0][1][19]),'{"U"}')
        actual=attrs.attribute_export(entry,type_references=REFS)
        self.assertEqual(s.render(attrs.attribute_xml(actual,type_references=REFS)[2]),s.render(entry))
        with self.assertRaisesRegex(ValueError,'Unresolved'):attrs.attribute_xml(attr)
        with self.assertRaisesRegex(ValueError,'Unresolved'):types.export_metadata(pattern,Q+'Type')

    def test_numeric_resource_rejects_later_reference_arm(self):
        top=E.Element(Q+'ChildObjects');node=attribute(top,['xs:boolean','cfg:CatalogRef.FreshCatalog'])
        profile={'allowed_type_codes':['B'],'defaults':{},'template':'unused'}
        with self.assertRaisesRegex(ValueError,'Unsupported inline scalar type'):inline.read(node,profile,type_references=REFS)

    def test_new_owners_reference_each_other_before_any_body_is_compiled(self):
        helper=cases.FinalNativeReferenceTests();r,_,owners,_,_=helper.case();self.addCleanup(helper.doCleanups)
        names={'Catalog':'FreshDocument','Document':'FreshCatalog'}
        for kind,name in names.items():
            file=Path(r['directory'])/commit.export.folder(kind)/('Fresh'+kind+'.xml')
            top=E.parse(file);other='Document' if kind=='Catalog' else 'Catalog'
            attribute(top.getroot()[0].find(Q+'ChildObjects'),['cfg:'+other+'Ref.'+name,'xs:boolean'])
            file.write_bytes(E.tostring(top.getroot(),encoding='utf-8'))
        import test_object_xml_profiles
        top=E.fromstring(test_object_xml_profiles.xml('Constant'));top[0].set('uuid',str(uuid.uuid4()));constant_id=top[0].get('uuid')
        top[0].remove(top[0].find(Q+'ChildObjects'));top[0].find(Q+'Properties/'+Q+'Name').text='FreshConstant'
        top[0].find(Q+'Properties').append(type_node(['cfg:CatalogRef.FreshCatalog']))
        file=Path(r['directory'])/'Constants/FreshConstant.xml';file.parent.mkdir(exist_ok=True);file.write_bytes(E.tostring(top,encoding='utf-8'))
        rootfile=Path(r['directory'])/'Configuration.xml';root=E.parse(rootfile);E.SubElement(root.getroot()[0].find(Q+'ChildObjects'),Q+'Constant').text='FreshConstant';root.write(rootfile,encoding='utf-8')
        plan,_=commit.prepare(r);r.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
        with patch.object(metadata,'allocate_creation',wraps=metadata.allocate_creation) as allocate:
            result=commit.serialize(r)
            self.assertEqual(allocate.call_count,4)
        _,records=batch.read_packet(result['data']);records={row.object_id:row for row in records}
        constant_meta=s.Parser(records[constant_id].metadata.decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.metadata_relations(constant_meta[14])[owners['Catalog']],0)
        bodies={kind:s.Parser(s.inflate(records[oid].body).decode('utf-8-sig')).documents()[0] for kind,oid in owners.items()}
        for kind in names:
            other='Document' if kind=='Catalog' else 'Catalog';layout=metadata.profiles.layout(other)
            expected=s.val(bodies[other][1][layout['generated_slots'][2]])
            attribute_body=bodies[kind][metadata.profiles.layout(kind)['inline_collections']['Attribute']['slot']][2]
            pattern=attribute_body[0][1][1][2]
            self.assertEqual(s.render(pattern),'{'+'"Pattern",{"B"},{"#",'+expected+'}}')
            meta=s.Parser(records[owners[kind]].metadata.decode('utf-8-sig')).documents()[0]
            self.assertEqual(s.metadata_relations(meta[14])[owners[other]],0)

    def test_single_owner_self_reference_and_cached_definition(self):
        r=owned.request();root=E.fromstring(r['object_xml']);name=root[0].findtext(Q+'Properties/'+Q+'Name')
        attribute(root[0].find(Q+'ChildObjects'),['cfg:CatalogRef.'+name])
        r['object_xml']=E.tostring(root,encoding='unicode')
        result=creation.serialize(r);_,records=batch.read_packet(result['data'])
        record=next(row for row in records if row.object_id==result['object_id']);body=s.Parser(s.inflate(record.body).decode('utf-8-sig')).documents()[0]
        layout=metadata.profiles.layout('Catalog');generated=s.val(body[1][layout['generated_slots'][2]])
        self.assertIn(generated,s.render(body[layout['inline_collections']['Attribute']['slot']]))

    def test_declaration_must_match_the_compiled_generated_ids(self):
        import metadata_context,metadata_targets
        r=owned.request();source=metadata_context.context_objects(r['context'])
        allocation=metadata.allocate_creation(r['object_xml'],r['platform'],'Catalog')
        targets=metadata_targets.creation('Catalog',allocation.object_id,allocation.name,{},source,r['object_id'])
        reader=native_references.Catalog(r,targets);reader.declare(allocation)
        self.assertEqual(reader.type_id('Catalog',allocation.name),allocation.generated[2])
        with self.assertRaisesRegex(ValueError,'Duplicate'):reader.declare(allocation)
        body=s.Parser(metadata.profiles.layout('Catalog')['template']).documents()[0]
        with self.assertRaises(ValueError):reader.register(allocation.object_id,s.native_body_bytes([body]),[])


if __name__=='__main__':unittest.main()
