"""Whole-CF differences identify bodies, arbitrary streams and dependencies."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
from compiled_image import Delta
import native_metadata as s

A='11111111-1111-4111-8111-111111111111'
B='22222222-2222-4222-8222-222222222222'


class CompiledImageTests(unittest.TestCase):
    def test_new_changed_deleted_streams_are_discovered_without_a_module_table(self):
        before={A:b'body',A+'.unknown':b'old',A+'.obsolete':b'removed',B:b'dependent',B+'.0':b'unchanged'}
        after={A:b'body',A+'.unknown':b'new',A+'.added':b'added',B:b'rebuilt dependent',B+'.0':b'unchanged'}
        delta=Delta(before,after,{A,B},{A,B},{})
        self.assertEqual(set(delta.objects),{A,B})
        self.assertFalse(delta.objects[A].body_changed)
        self.assertEqual(delta.objects[A].added_streams,(A+'.added',))
        self.assertEqual(delta.objects[A].removed_streams,(A+'.obsolete',))
        self.assertEqual(delta.objects[A].changed_streams,(A+'.unknown',))
        self.assertTrue(delta.objects[B].body_changed)

    def test_creation_and_complete_deletion_include_all_streams(self):
        delta=Delta({A:b'old',A+'.1':b'old stream'},{B:b'new',B+'.arbitrary':b'new stream'},{A},{B},{})
        self.assertEqual(delta.objects[A].operation,'delete');self.assertEqual(delta.objects[B].operation,'create')
        with self.assertRaisesRegex(ValueError,'retains records'):
            Delta({A:b'old'},{A+'.1':b'orphan'},{A},set(),{})

    def test_known_external_names_have_explicit_ownership_and_unknown_records_fail(self):
        metadata=[s.atom(0) for _ in range(17)];metadata[1]=s.atom(A);metadata[13]=[s.atom(0)]
        metadata[11]=[s.atom(1),s.atom('external-payload',True),s.atom(s.ZERO)]
        delta=Delta({A:b'body','external-payload':b'old'},{A:b'body','external-payload':b'new'},{A},{A},{A:[metadata]})
        self.assertEqual(delta.objects[A].changed_streams,('external-payload',))
        with self.assertRaisesRegex(ValueError,'Unclassified'):
            Delta({A:b'body'},{A:b'body','unowned-record':b'data'},{A},{A},{})

    def test_new_stream_of_declared_root_feature_belongs_to_configuration(self):
        metadata=[s.atom(0) for _ in range(17)];metadata[1]=s.atom(A)
        metadata[11]=[s.atom(0)];metadata[13]=[s.atom(1),s.atom(B)]
        delta=Delta({A:b'body'},{A:b'body',B+'.7':b'session module'},{A},{A},{A:[metadata]})
        self.assertEqual(delta.objects[A].added_streams,(B+'.7',))
        self.assertEqual(delta.records[B+'.7'],A)

    def test_service_version_list_is_not_an_object_but_cf_identity_cannot_change(self):
        delta=Delta({A:b'body','versions':b'old'},{A:b'body','versions':b'new'},{A},{A},{})
        self.assertFalse(delta.objects)
        with self.assertRaisesRegex(ValueError,'identity/format'):
            Delta({A:b'body','root':b'configuration'},{A:b'body','root':b'other'},{A},{A},{})


if __name__=='__main__':unittest.main()
