"""Tabular RLS paths retain both section and leaf identities."""
import copy,json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(next(p for p in (Path(__file__).resolve().parents[1]/'src').iterdir() if (p/'role_metadata_context.py').exists())))
import metadata_definitions as defs
import role_metadata_context as metadata
import role_rights_xml as rights
import role_rights_native as native
import native_metadata as s
from test_metadata_definitions import fixture,oid


class NestedRoleFieldTests(unittest.TestCase):
    def test_whole_file_matches_independent_native_compilation(self):
        case=json.loads(Path(__file__).with_name('fixtures').joinpath('role_nested_field_851.json').read_text())
        index=defs.Index(defs.Definition(**row) for row in case['definitions']);ctx=metadata.Context(index)
        raw=rights.compile(case['xml'],ctx)
        self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()[0]),s.render(s.Parser(case['body']).documents()[0]))
        path=ctx.field_path(case['owner'],case['field']);self.assertEqual(ctx.field_name(case['owner'],path),case['field'])
        self.assertEqual(len(ctx.field(case['owner'],case['field']).ancestors),1)
        dependencies=native.file_references(raw)
        self.assertEqual(dependencies,frozenset(row['object_id'] for row in case['definitions'] if row['kind']!='Configuration'))
        self.assertEqual({row['object_id'] for row in rights.required_definitions(case['xml'],index)},{row['object_id'] for row in case['definitions']})

    def test_paths_reject_foreign_sections_foreign_leaves_and_stored_objects(self):
        ctx=metadata.Context(defs.from_inventory(fixture()));path=ctx.field_path('Catalog.Items','Rows.Amount')
        with self.assertRaisesRegex(ValueError,'another metadata owner'):ctx.field_name('Task.Jobs',path)
        for target in [oid(13),oid(2)]:
            bad=copy.deepcopy(path);bad[1][1]=s.atom(target)
            with self.assertRaises(ValueError):ctx.field_name('Catalog.Items',bad)
        bad=copy.deepcopy(path);bad[0][1]=s.atom(oid(13))
        with self.assertRaises(ValueError):ctx.field_name('Catalog.Items',bad)

    def test_unmapped_nested_standard_deeper_and_missing_paths_fail(self):
        ctx=metadata.Context(defs.from_inventory(fixture()))
        for name in ['Rows.LineNumber','Rows.Missing','Missing.Amount','Rows..Amount','Rows.Amount.More']:
            with self.subTest(name=name),self.assertRaises(ValueError):ctx.field_path('Catalog.Items',name)
        with self.assertRaises(ValueError):ctx.field_name('Catalog.Items',[[s.atom(0),s.atom(oid(11))],[s.atom(-1)]])

    def test_reference_reader_requires_real_nonzero_ancestry_ids(self):
        case=json.loads(Path(__file__).with_name('fixtures').joinpath('role_nested_field_851.json').read_text())
        body=s.Parser(case['body']).documents()[0];table=native.read(body[1][1][1]);matrix=table.restrictions[0][1];matrix[2][3][0][1]=s.atom(s.ZERO);body[1][1][1]=native.write(table)
        with self.assertRaisesRegex(ValueError,'Zero native role table'):native.file_references(s.native_body_bytes([body]))


if __name__=='__main__':unittest.main()
