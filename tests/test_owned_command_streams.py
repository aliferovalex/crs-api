"""Preservation proves command-owned streams from the actual native owner."""
import base64,copy,json,unittest,uuid
from pathlib import Path
import test_object_change_serializer as source
import inline_command_xml as commands
import native_metadata as s
import object_xml_profiles as profiles


class OwnedCommandStreamTests(unittest.TestCase):
    def fixture(self,label='Mixed'):
        rows=json.loads(Path(__file__).with_name('fixtures').joinpath('characteristic_children_851.json').read_text(encoding='utf-8'))['samples']
        case=next(row for row in rows if row['label']==label);kind=case['kind']
        request,docs,raw=source.fixture(kind,case['xml']);body=s.Parser(raw.decode('utf-8-sig')).documents()[0];oid=request['object_id']
        owned=commands.streams(body,profiles.layout(kind));names=[oid+'.15']+list(owned.values());version='bbbbbbbb-cccc-4ddd-8eee-ffffffffffff'
        docs[0][11]=[s.atom(len(names))];docs[2]=[s.atom(len(names))]
        for name in names:
            docs[0][11].extend([s.atom(name,True),s.atom(version)])
            docs[2].append([s.atom(name,True),s.atom(version),s.atom(1)])
        return docs,body,oid,kind,names,version

    def test_modules_of_one_two_and_mixed_commands_keep_their_versions(self):
        for label in ('Command','TwoCommands','Mixed','Default'):
            with self.subTest(label=label):
                docs,body,oid,kind,names,version=self.fixture(label);features=s.render(docs[0][13]);before=s.render(body)
                result=commands.preserve_owner_streams(docs,oid,body,kind,'8.5.1.1529')
                expected=(uuid.UUID(version).bytes_le+bytes(4)).hex()
                self.assertEqual(result,[dict(name=name,version=expected,action=0) for name in names])
                self.assertEqual(s.render(docs[2]),'{0}');self.assertEqual(s.render(body),before)
                self.assertEqual(s.render(docs[0][13]),features)
                for value in docs[0][11][2::2]:self.assertEqual(base64.b64decode(s.val(value)).hex(),expected)

    def test_foreign_uuid_wrong_suffix_and_non_command_features_cannot_own_streams(self):
        for replace in ('aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee.2',None):
            docs,body,oid,kind,names,_=self.fixture();bad=replace or names[-1].removesuffix('.2')+'.0'
            docs[0][11][-2]=s.atom(bad,True);docs[2][-1][0]=s.atom(bad,True)
            with self.assertRaisesRegex(ValueError,'external object map'):commands.preserve_owner_streams(docs,oid,body,kind,'8.5.1.1529')
        docs,body,oid,kind,_,_=self.fixture();doc=copy.deepcopy(docs);doc[0][13]=[s.atom(0)]
        with self.assertRaisesRegex(ValueError,'absent from the feature map'):commands.preserve_owner_streams(doc,oid,body,kind,'8.5.1.1529')

    def test_malformed_collection_counter_or_repeated_command_is_rejected(self):
        docs,body,oid,kind,_,_=self.fixture();slot=profiles.layout(kind)['command_collections']['Command']['slot']
        broken=copy.deepcopy(body);broken[slot][1]=s.atom(0)
        with self.assertRaisesRegex(ValueError,'command collection'):commands.preserve_owner_streams(copy.deepcopy(docs),oid,broken,kind,'8.5.1.1529')
        broken=copy.deepcopy(body);broken[slot].append(copy.deepcopy(broken[slot][2]));broken[slot][1]=s.atom(2)
        with self.assertRaisesRegex(ValueError,'Duplicate owner command'):commands.preserve_owner_streams(copy.deepcopy(docs),oid,broken,kind,'8.5.1.1529')
