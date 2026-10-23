"""Qualified form references bind to the current owner's registered children."""
import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('metadata_object_xml.py')).parent))
import metadata_context
import metadata_identifiers
import xml_namespaces
import native_metadata as s
import metadata_object_xml as flat
import v8unpack_backend as backend
from xml.etree import ElementTree as E
import metadata_targets,object_change_serializer as changes
from test_managed_form_creation import store
import base64,uuid


class OwnedFormReferenceTests(unittest.TestCase):
    def setUp(self):
        self.data=json.loads(Path(__file__).with_name('fixtures').joinpath('owner_form_references_851.json').read_text(encoding='utf-8'))
        self.objects={oid:[s.Parser(text).documents()[0],[s.atom(0)],[s.atom(0)]] for oid,text in self.data['objects'].items()}
        # The old name-resolution witness used identity-only placeholders.
        # Give it real descriptor shapes for snapshot/version-bound tests.
        for docs in self.objects.values():
            m=docs[0];m[0]=s.atom(5);m[4]=s.atom(s.ZERO);m[5]=m[6]=s.atom(1)
            m[7]=m[8]=s.atom('11111111-2222-4333-8444-555555555555')
            if s.val(m[3])=='0':m[3]=s.atom('99999999-aaaa-4bbb-8ccc-dddddddddddd')
            for slot in (11,12,13):
                if not isinstance(m[slot],list):m[slot]=[s.atom(0)]
            refs=[s.val(m[3])]+[oid for oid,_ in metadata_context.children(m)]
            m[14]=[s.atom(len(refs))]+[s.atom(oid) for oid in refs]+[s.atom(1) for _ in refs]
        for docs in self.objects.values():
            counts={}
            for oid,cls in metadata_context.children(docs[0]):
                self.objects[oid][0][10]=s.atom(counts.get(cls,0));counts[cls]=counts.get(cls,0)+1

    def test_full_owner_bodies_match_independent_native_references(self):
        for case in self.data['cases']:
            with self.subTest(kind=case['kind']):
                body=flat.object_xml(case['xml'],'8.5.1.1529',case['kind'],self.objects)[2]
                self.assertEqual(backend.signature(s.Parser(body.decode('utf-8-sig')).documents()),backend.signature(s.Parser(case['body']).documents()))

    def test_reference_cannot_use_another_owner_with_same_form_name(self):
        for case in self.data['cases']:
            with self.subTest(kind=case['kind']):
                objects=copy.deepcopy(self.objects);owner=objects[case['owner_id']][0]
                fid=s.val(owner[12][1][2]);foreign='77777777-7777-4777-8777-777777777777'
                objects[fid][0][3]=s.atom(foreign)
                with self.assertRaisesRegex(ValueError,'owned form reference'):
                    flat.object_xml(case['xml'],'8.5.1.1529',case['kind'],objects)

    def test_reference_requires_owner_registration(self):
        for case in self.data['cases']:
            objects=copy.deepcopy(self.objects);objects[case['owner_id']][0][12]=[s.atom(0)]
            with self.assertRaisesRegex(ValueError,'owned form reference'):
                flat.object_xml(case['xml'],'8.5.1.1529',case['kind'],objects)

    def test_owned_reference_rejects_wrong_path_and_owner_name(self):
        case=self.data['cases'][0]
        for text in (case['xml'].replace('.Form.','.Unknown.'),case['xml'].replace('DataProcessor.CRSAPI_ProfileProcessor.Form.','DataProcessor.OtherOwner.Form.')):
            with self.assertRaises(ValueError):flat.object_xml(text,'8.5.1.1529',case['kind'],self.objects)

    def final_index(self,case):
        records={}
        for oid,docs in self.objects.items():
            kind=metadata_identifiers.class_labels()[s.val(docs[0][2])]
            records[oid]=dict(id=oid,kind='Form' if kind.endswith('Form') else kind,name=s.val(docs[0][9]),parent_id=s.val(docs[0][3]))
        fid='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
        records[fid]=dict(id=fid,kind='Form',name='NewDefault',parent_id=case['owner_id'])
        return metadata_targets.final(self.objects,records),fid

    def test_existing_owner_can_select_a_new_form_without_fabricating_context_versions(self):
        for case in self.data['cases']:
            with self.subTest(kind=case['kind']):
                before=s.render(self.objects[case['owner_id']]);index,fid=self.final_index(case)
                q='{'+xml_namespaces.MD+'}';root=E.fromstring(case['xml']);props=root[0].find(q+'Properties')
                for key in ('DefaultForm','AuxiliaryForm'):
                    props.find(q+key).text=case['kind']+'.'+s.val(self.objects[case['owner_id']][0][9])+'.Form.NewDefault'
                request=dict(platform='8.5.1.1529',object_type=case['kind'],object_id=case['owner_id'],
                             context=base64.b64encode(s.storage([s.text_bytes(d) for d in self.objects.values()],s.text_bytes([[s.atom(0)]]))).decode(),
                             snapshot=store(self.objects[case['owner_id']],case['body'].encode('utf-8')),
                             original_version=uuid.UUID(s.val(self.objects[case['owner_id']][0][7])).bytes_le.hex()+'00000000',
                             object_xml=E.tostring(root,encoding='unicode'))
                with self.assertRaisesRegex(ValueError,'owned form reference'):changes.serialize(request,native_content=True)
                docs,raw,_,_=changes.serialize(request,native_content=True,reference_objects=index)
                body=s.Parser(raw.decode('utf-8-sig')).documents()[0]
                layout=flat.profiles.layout(case['kind'])
                for key in ('DefaultForm','AuxiliaryForm'):
                    value=body
                    for slot in layout['reference_values'][key]['path']:value=value[slot]
                    self.assertEqual(s.val(value),fid)
                self.assertIn(fid,s.metadata_relations(docs[0][14]));self.assertEqual(s.render(self.objects[case['owner_id']]),before)

    def test_final_index_does_not_resolve_deleted_children_or_accept_changed_source_identity(self):
        case=self.data['cases'][0];index,_=self.final_index(case)
        missing=metadata_targets.Index(row for row in index.targets if row.parent_id!=case['owner_id'])
        with self.assertRaisesRegex(ValueError,'owned form reference'):flat.object_xml(case['xml'],'8.5.1.1529',case['kind'],missing)
        records={oid:dict(kind=('Form' if metadata_identifiers.class_labels()[s.val(d[0][2])].endswith('Form') else metadata_identifiers.class_labels()[s.val(d[0][2])]),parent_id=s.val(d[0][3]),name=s.val(d[0][9])) for oid,d in self.objects.items()}
        records[case['owner_id']]['name']='Changed'
        with self.assertRaisesRegex(ValueError,'identity differs'):metadata_targets.final(self.objects,records)


if __name__=='__main__':unittest.main()
