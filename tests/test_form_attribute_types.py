"""Native 8.5.1 witnesses for compound and generated reference form types."""
import base64,copy,hashlib,json,sys,unittest,uuid
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import metadata_context
import native_metadata as s, metadata_identifiers as ids
import metadata_references as refs,form_attribute_types as references,type_description_xml as types
import managed_form_xml as forms
import managed_form_profiles as profiles
import test_object_creation_serializer as constants
from test_form_kinds_xml import common_xml,native


class FormAttributeTypesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.witness=json.loads(Path(__file__).with_name('fixtures').joinpath('form_attribute_types_851.json').read_text(encoding='utf-8'))

    def fixture(self):
        source=constants.fixture('8.5.1.1529');seed=metadata_context.context_metadata(base64.b64decode(source['context']),source['object_id'])
        records=[];context=[];snapshots={};manifest=[s.atom(0),s.atom(len(self.witness['objects']))]
        for index,obj in enumerate(self.witness['objects']):
            docs=copy.deepcopy(seed);m=docs[0];oid=obj['object_id'];cls=ids.class_id(obj['kind'])
            m[1]=s.atom(oid);m[2]=s.atom(cls);m[3]=s.atom(source['object_id']);m[9]=s.atom(obj['name'],True);m[10]=s.atom(index)
            for slot in (11,12,13,14):m[slot]=[s.atom(0)]
            m[15]=s.atom(cls+'.'+obj['name'],True)
            meta=s.text_bytes(docs);body=s.compress(s.native_body_bytes(s.Parser(obj['body']).documents()))
            row=[s.atom(oid),s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(body).hexdigest(),True),s.atom(0)]
            snapshots[oid]=base64.b64encode(s.storage([meta,body],s.text_bytes([[s.atom(0),s.atom(1)]+row]))).decode()
            records.extend([meta,body]);context.append(meta);manifest.extend(row)
        return dict(context=base64.b64encode(s.storage(context,s.text_bytes([[s.atom(0)]]))).decode(),reference_snapshots=snapshots),s.storage(records,s.text_bytes([manifest]))

    def xml(self):
        root=E.fromstring(common_xml(()));attrs=root.find(forms.Q+'Attributes')
        for index,case in enumerate(self.witness['cases'],1):
            attr=E.SubElement(attrs,forms.Q+'Attribute',name=case['name'],id=str(index));attr.append(E.fromstring(case['xml']))
            field=E.SubElement(root.find(forms.Q+'ChildItems'),forms.Q+'InputField',name=case['name'],id=str(index+100))
            E.SubElement(field,forms.Q+'DataPath').text=case['name']
        return E.tostring(root,encoding='unicode')

    def test_native_patterns_match_and_scalar_profiles_remain_strict(self):
        request,_=self.fixture();resolved=refs.resolve(self.xml(),request)
        for case in self.witness['cases']:
            with self.subTest(name=case['name']):
                node=E.fromstring(case['xml'])
                self.assertEqual(s.render(types.read_form(node,resolved)),case['pattern'])
                # Assembly order is deterministic; XML type order is not semantic.
                node[:]=list(reversed(list(node)))
                self.assertEqual(s.render(types.read_form(node,resolved)),case['pattern'])
                if case['name']!='Moment':
                    with self.assertRaises(ValueError):types.read(node)

    def test_creation_snapshots_and_change_storage_resolve_identical_types(self):
        request,storage=self.fixture();xml=self.xml()
        snapshots=refs.resolve(xml,request);self.assertEqual(snapshots,refs.resolve(xml,request,storage))
        expected_ids={obj['object_id'] for obj in self.witness['objects']}
        self.assertEqual({row['object_id'] for row in refs.plan(dict(request,xml=xml))['objects']},expected_ids)
        self.assertTrue(set(snapshots.values()).isdisjoint(expected_ids))
        paths=forms.ObjectPaths();paths.references=snapshots
        converted=forms.interface(forms.convert(native('CommonForm'),xml,paths=paths,kind='CommonForm'))
        self.assertEqual([s.render(a[5]) for a in converted[3][2:6]],[c['pattern'] for c in self.witness['cases']])

    def test_missing_objects_snapshots_and_stale_versions_rejected(self):
        request,storage=self.fixture();xml=self.xml()
        with self.assertRaisesRegex(ValueError,'snapshot is required'):refs.resolve(xml,dict(request,reference_snapshots={}))
        with self.assertRaisesRegex(ValueError,'missing from current context'):refs.resolve(xml.replace('CRSAPI_TestCatalog','Missing'),request)
        context=base64.b64decode(request['context']);records=[];offset=12
        for _ in self.witness['objects']:
            raw,offset=s.read_record(context,offset);docs=s.Parser(raw.decode('utf-8-sig')).documents();docs[0][7]=s.atom('33333333-3333-4333-8333-333333333333');records.append(s.text_bytes(docs))
        changed=dict(request,context=base64.b64encode(s.storage(records,s.text_bytes([[s.atom(0)]]))).decode())
        with self.assertRaisesRegex(ValueError,'snapshot/context mismatch'):refs.resolve(xml,changed)
        with self.assertRaisesRegex(ValueError,'storage/context mismatch'):refs.resolve(xml,changed,storage)

    def test_invalid_compounds_references_and_orphan_qualifiers_rejected(self):
        request,_=self.fixture();case=self.witness['cases'][0];node=E.fromstring(case['xml']);resolved=refs.resolve(self.xml(),request)
        for mutation in ('duplicate','qualifier','orphan','unknown','unresolved'):
            target=copy.deepcopy(node)
            if mutation=='duplicate':target.append(copy.deepcopy(target[0]))
            elif mutation=='qualifier':target.append(copy.deepcopy(target[-1]))
            elif mutation=='orphan':target[:]=[n for n in target if n.tag!=types.Q+'Type' or n.text!='xs:string']
            elif mutation=='unknown':E.SubElement(target,types.Q+'Unexpected')
            else:next(n for n in target if (n.text or '').startswith('cfg:')).text='cfg:CatalogRef.Missing'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):types.read_form(target,resolved)
        with self.assertRaisesRegex(ValueError,'Unsupported form reference type'):refs.plan(dict(request,xml=self.xml().replace('CatalogRef','CatalogObject')))
        # A main Object is resolved by the owner, not treated as an additional Ref.
        root=E.fromstring(self.xml());attr=root.find(forms.Q+'Attributes')[0];E.SubElement(attr,forms.Q+'MainAttribute').text='true'
        for node in attr.find(forms.Q+'Type'):
            if (node.text or '').startswith('cfg:'):node.text='cfg:CatalogObject.CRSAPI_TestCatalog'
        self.assertNotIn('cfg:CatalogObject.CRSAPI_TestCatalog',references.required(E.tostring(root,encoding='unicode')))

    def test_body_identity_and_generated_id_collisions_rejected(self):
        request,_=self.fixture();objects=metadata_context.context_objects(request['context'])
        for obj in self.witness['objects']:
            body=s.Parser(obj['body']).documents()[0];m=objects[obj['object_id']][0]
            with self.subTest(kind=obj['kind']):
                for replacement in (body[1][1],s.atom(obj['object_id']),s.atom(s.ZERO)):
                    broken=copy.deepcopy(body);broken[1][2]=replacement
                    with self.assertRaisesRegex(ValueError,'generated reference type UUID'):references.generated_type(broken,m,obj['kind'])
                wrong=copy.deepcopy(m);wrong[9]=s.atom('Wrong',True)
                with self.assertRaisesRegex(ValueError,'identity mismatch'):references.generated_type(body,wrong,obj['kind'])

    def test_reference_types_follow_another_context_without_cached_repository_ids(self):
        original,_=self.fixture();before=refs.resolve(self.xml(),original)
        alternate=type(self)();alternate.witness=copy.deepcopy(self.witness);expected={}
        for obj in alternate.witness['objects']:
            body=s.Parser(obj['body']).documents()[0]
            oid=str(uuid.uuid5(uuid.NAMESPACE_URL,'other-repository/'+obj['kind']))
            obj['object_id']=oid;profiles.owner_common(body,obj['kind'])[1][2]=s.atom(oid)
            layout=json.loads(Path(types.__file__).with_name(obj['kind'].lower()+'_layout_851.json').read_text(encoding='utf-8'))
            for slot in layout['generated_slots']:
                body[1][slot]=s.atom(str(uuid.uuid5(uuid.NAMESPACE_URL,'other-repository/'+obj['kind']+'/'+str(slot))))
            obj['body']=s.render(body)
            categories=layout.get('generated_categories',('Object','Ref','Selection','List','Manager'))
            expected['cfg:'+obj['kind']+'Ref.'+obj['name']]=s.val(body[1][layout['generated_slots'][list(categories).index('Ref')*2]])
        request,storage=alternate.fixture()
        self.assertEqual(refs.resolve(self.xml(),request),expected)
        self.assertEqual(refs.resolve(self.xml(),request,storage),expected)
        self.assertTrue(set(before.values()).isdisjoint(expected.values()))


if __name__=='__main__':unittest.main()
