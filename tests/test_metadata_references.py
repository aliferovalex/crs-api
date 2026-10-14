"""Resolve enum values using native bodies and current snapshot/version guards."""
import base64
import copy
import hashlib
import json
import sys
import unittest
import uuid
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(next((Path(__file__).resolve().parents[1]/'src').rglob('metadata_references.py')).parent))
import metadata_serializer as s
import metadata_references as refs
import managed_form_xml as x
import managed_form_elements as elements
import v8unpack_backend as b


class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=Path(__file__).with_name('fixtures')
        cls.witness=json.loads((folder/'form_enum_references_851.json').read_text(encoding='utf-8'))['cases']
        cls.interfaces=json.loads((folder/'form_enum_choice_interfaces_851.json').read_text(encoding='utf-8'))
        cls.base=json.loads((folder/'form_rules_851.json').read_text(encoding='utf-8'))

    def fixture(self):
        objects=[];snapshots={};records=[];manifest=[s.atom(0),s.atom(len(self.witness))]
        version='11111111-1111-4111-8111-111111111111'
        for case in self.witness:
            m=s.Parser(case['metadata']).documents()[0];m[0]=s.atom(5);m[3]=s.atom('22222222-2222-4222-8222-222222222222')
            m[5]=m[6]=s.atom(1);m[7]=m[8]=s.atom(version)
            for i in (11,12,14):m[i]=[s.atom(0)]
            docs=[m,[s.atom(0)],[s.atom(0)]];meta=s.text_bytes(docs);body=s.compress(s.native_body_bytes(s.Parser(case['body']).documents()))
            oid=s.val(m[1]);row=[s.atom(oid),s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(body).hexdigest(),True),s.atom(0)]
            snapshots[oid]=base64.b64encode(s.storage([meta,body],s.text_bytes([[s.atom(0),s.atom(1)]+row]))).decode()
            records.extend([meta,body]);manifest.extend(row);objects.append(docs)
        context=base64.b64encode(s.storage([s.text_bytes(d) for d in objects],s.text_bytes([[s.atom(0)]]))).decode()
        return dict(context=context,reference_snapshots=snapshots),s.storage(records,s.text_bytes([manifest]))

    def test_snapshot_and_version_storage_resolve_same_native_references(self):
        request,storage=self.fixture()
        for case in self.interfaces['cases']:
            with self.subTest(xml=case['xml'][:20]):
                from_snapshot=refs.resolve(case['xml'],request);from_version=refs.resolve(case['xml'],request,storage)
                self.assertEqual(from_snapshot,from_version)
                for type_id,value_id in from_snapshot.values():
                    self.assertNotIn(type_id,request['reference_snapshots'])
                    uuid.UUID(type_id);uuid.UUID(value_id)

    def test_complete_enum_interfaces_match_native_hashes(self):
        request,_=self.fixture()
        for case in self.interfaces['cases']:
            paths=x.ObjectPaths({k:s.Parser(v).documents()[0] for k,v in self.base['paths'].items()});paths.types=self.base['types'];paths.tables=set(self.base['tables'])
            paths.references=refs.resolve(case['xml'],request)
            raw=x.convert(self.interfaces['base'].encode('utf-8'),case['xml'],paths=paths,object_name='CRSAPI_FullCatalog')
            signature=b.signature(s.Parser(raw.decode('utf-8-sig')).documents())
            self.assertEqual(hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest(),case['sha256'])

    def test_missing_value_snapshot_or_context_enum_fails(self):
        request,_=self.fixture();xml=self.interfaces['cases'][0]['xml']
        with self.assertRaisesRegex(ValueError,'snapshot is required'):refs.resolve(xml,dict(request,reference_snapshots={}))
        missing=xml.replace('.EnumValue.','.EnumValue.Missing',1)
        with self.assertRaisesRegex(ValueError,'value is missing'):refs.resolve(missing,request)
        with self.assertRaisesRegex(ValueError,'missing from current context'):refs.resolve(xml.replace('Enum.','Enum.Missing',1),request)

    def test_stale_snapshot_and_stale_complete_version_are_rejected(self):
        request,storage=self.fixture();xml=self.interfaces['cases'][0]['xml']
        data=base64.b64decode(request['context']);documents=[];pos=12
        for _ in self.witness:
            raw,pos=s.read_record(data,pos);docs=s.Parser(raw.decode('utf-8-sig')).documents();docs[0][7]=s.atom('33333333-3333-4333-8333-333333333333');documents.append(docs)
        request['context']=base64.b64encode(s.storage([s.text_bytes(d) for d in documents],s.text_bytes([[s.atom(0)]]))).decode()
        with self.assertRaisesRegex(ValueError,'snapshot/context mismatch'):refs.resolve(xml,request)
        with self.assertRaisesRegex(ValueError,'storage/context mismatch'):refs.resolve(xml,request,storage)

    def test_features_and_body_identity_are_validated(self):
        case=self.witness[0];body=s.Parser(case['body']).documents()[0];meta=s.Parser(case['metadata']).documents()[0]
        broken=copy.deepcopy(body);broken[1][1]=broken[1][2]
        with self.assertRaisesRegex(ValueError,'generated type'):refs.add_enum({},broken,meta)
        broken=copy.deepcopy(body);broken[1][5][1][2]=s.atom('WrongName',True)
        with self.assertRaisesRegex(ValueError,'identity mismatch'):refs.add_enum({},broken,meta)
        broken=copy.deepcopy(body);broken[6].append(copy.deepcopy(broken[6][2]));broken[6][1]=s.atom(len(broken[6])-2)
        with self.assertRaisesRegex(ValueError,'value/features'):refs.add_enum({},broken,meta)

    def test_reference_free_xml_does_not_require_context_or_snapshots(self):
        self.assertEqual(refs.resolve(None,{}),{})
        self.assertEqual(refs.resolve('<Form/>',{}),{})
        with self.assertRaises(ValueError):refs.required('<!DOCTYPE Form><Form/>')

    def test_removed_enum_value_requires_matching_feature_map(self):
        case=self.witness[0];body=s.Parser(case['body']).documents()[0];meta=s.Parser(case['metadata']).documents()[0]
        removed=body[6].pop();body[6][1]=s.atom(len(body[6])-2)
        removed_id=s.val(removed[0][1][1][2])
        with self.assertRaisesRegex(ValueError,'feature map differs'):refs.add_enum({},body,meta)
        meta[13]=[s.atom(len(body[6])-2)]+[s.atom(s.val(value[0][1][1][2])) for value in body[6][2:]]
        mapping={};refs.add_enum(mapping,body,meta)
        self.assertNotIn(removed_id,[value_id for _,value_id in mapping.values()])
        self.assertEqual(len(mapping),len(body[6])-2)

    def test_enum_value_uuid_cannot_reuse_generated_type_or_object_id(self):
        case=self.witness[0]
        for slot in (1,None):
            body=s.Parser(case['body']).documents()[0];meta=s.Parser(case['metadata']).documents()[0]
            replacement=body[1][slot] if slot is not None else meta[1]
            old=s.val(body[6][2][0][1][1][2]);body[6][2][0][1][1][2]=replacement
            meta[13]=[replacement if s.val(value)==old else value for value in meta[13]]
            with self.assertRaisesRegex(ValueError,'value/features'):refs.add_enum({},body,meta)

    def test_plan_deduplicates_enum_objects_and_uses_metadata_uuid(self):
        request,_=self.fixture();xml=self.interfaces['cases'][0]['xml']
        result=refs.plan(dict(request,xml=xml))
        self.assertEqual(len(result['objects']),1)
        self.assertEqual(result['objects'][0]['object_id'],self.witness[0]['object_id'])
        self.assertEqual(refs.plan({'xml':'<Form/>'}),{'objects':[]})


if __name__=='__main__':unittest.main()
