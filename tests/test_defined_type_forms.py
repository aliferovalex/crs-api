"""TypeSet form attributes use verified generated type identities."""
import base64
import copy
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree as E
import test_defined_types as types
import test_constant_change as source
import form_attribute_types as references
import managed_form_xml as forms
import metadata_context
import metadata_references
import native_metadata as s
from test_managed_form_creation import store


def signature(node):
    if isinstance(node,list):return tuple(signature(child) for child in node)
    value=s.val(node)
    # Base64 line wrapping is formatting; compare every decoded byte instead.
    if value.startswith('#base64:'):value=base64.b64decode(value[8:])
    return node.quoted,value


class DefinedTypeFormTests(unittest.TestCase):
    def witness(self):
        return json.loads(Path(__file__).with_name('fixtures').joinpath('defined_type_form_851.json').read_text(encoding='utf-8'))

    def request(self):
        request,seed,_=source.ConstantChangeTests().fixture();records=[];snapshots={}
        for case in types.DefinedTypeTests().samples()[:2]:
            docs=copy.deepcopy(seed);m=docs[0];m[1]=s.atom(case['id']);m[2]=s.atom(types.ids.class_id('DefinedType'));m[9]=s.atom(case['name'],True);m[13]=[s.atom(0)]
            records.append(s.text_bytes(docs));snapshots[case['id']]=store(docs,case['body'].encode('utf-8-sig'))
        request.update(platform='8.5.1.1529',context=base64.b64encode(s.storage(records,s.text_bytes([[s.atom(0)]]))).decode(),reference_snapshots=snapshots)
        return request

    def test_native_whole_form_matches_and_dependencies_are_metadata_objects(self):
        case=self.witness();request=self.request();resolved=metadata_references.resolve(case['xml'],request)
        self.assertEqual(set(resolved),{'cfg:DefinedType.ProbeAlias','cfg:DefinedType.ProbeComposite'})
        planned=metadata_references.plan(dict(request,xml=case['xml']))
        self.assertEqual({row['object_id'] for row in planned['objects']},{row['id'] for row in types.DefinedTypeTests().samples()[:2]})
        paths=forms.object_paths(None,'CommonForm');paths.references=resolved
        raw=forms.convert(case['interface'].encode('utf-8-sig'),case['xml'],paths=paths,kind='CommonForm')
        self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(case['interface']).documents()))

    def test_common_form_and_defined_types_compile_in_one_configuration_packet(self):
        import test_final_native_references as cases
        import configuration_commit as commit
        import configuration_batch as batch
        helper=cases.FinalNativeReferenceTests();request,_,_,_,_=helper.case();self.addCleanup(helper.doCleanups)
        directory=Path(request['directory']);path=directory/'Configuration.xml';root=E.parse(path);children=root.getroot()[0].find(types.objects.Q+'ChildObjects')
        for case in types.DefinedTypeTests().samples()[:2]:
            folder=directory/'DefinedTypes';folder.mkdir(exist_ok=True);(folder/(case['name']+'.xml')).write_text(case['xml'],encoding='utf-8')
            E.SubElement(children,types.objects.Q+'DefinedType').text=case['name']
        case=self.witness();folder=directory/'CommonForms';folder.mkdir(exist_ok=True);(folder/'ProbeAliasForm.xml').write_text(case['definition'],encoding='utf-8')
        ext=folder/'ProbeAliasForm/Ext';(ext/'Form').mkdir(parents=True);(ext/'Form.xml').write_text(case['xml'],encoding='utf-8');(ext/'Form/Module.bsl').write_bytes(b'// DefinedType form module\r\n')
        E.SubElement(children,types.objects.Q+'CommonForm').text='ProbeAliasForm';root.write(path,encoding='utf-8')
        plan,_=commit.prepare(request);request.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
        _,records=batch.read_packet(commit.serialize(request)['data']);record=next(row for row in records if row.object_id==case['id'])
        relations=s.metadata_relations(s.Parser(record.metadata.decode('utf-8-sig')).documents()[0][14])
        for row in types.DefinedTypeTests().samples()[:2]:self.assertEqual(relations[row['id']],1)
        native_relations=s.metadata_relations(s.Parser(case['metadata']).documents()[0][14])
        self.assertEqual(set(relations.values()),set(native_relations.values()))
        actual=s.inflate(dict(record.externals)[case['id']+'.0'])
        self.assertEqual(signature(s.Parser(actual.decode('utf-8-sig')).documents()),signature(s.Parser(case['interface']).documents()))

    def test_removing_a_typeset_drops_only_its_proven_native_relation(self):
        case=self.witness();request=self.request();metadata=s.Parser(case['metadata']).documents()[0]
        parent=s.val(metadata[3]);previous=s.metadata_relations(metadata[14]);root=E.fromstring(case['xml'])
        attrs=root.find(forms.Q+'Attributes');attrs.remove(next(node for node in attrs if node.get('name')=='ProbeComposite'))
        opaque='77777777-7777-4777-8777-777777777777';previous[opaque]=0
        actual=s.metadata_relations(metadata_references.form_relations(E.tostring(root,encoding='unicode'),request,parent,previous,case['interface'].encode('utf-8-sig')))
        alias,composite,_=types.DefinedTypeTests().samples()
        self.assertEqual(actual,{parent:1,alias['id']:1,opaque:0})
        self.assertNotIn(composite['id'],actual)
        request['reference_snapshots']={}
        with self.assertRaisesRegex(ValueError,'snapshot is required'):
            metadata_references.form_relations(E.tostring(root,encoding='unicode'),request,parent,previous,case['interface'].encode('utf-8-sig'))


if __name__=='__main__':unittest.main()
