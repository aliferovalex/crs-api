"""Native comparison covers all object classes without XML serializers."""
import base64
import sys
import unittest
import subprocess
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import object_changes as changes
from test_repository_cache import snapshot, docs, CHILD, ROOT, OLD
from test_version_labels import OSCRIPT, ROOT as PROJECT


class ObjectChangesTests(unittest.TestCase):
    def frame(self, body=b'body', streams=None):
        streams = streams or {}
        return snapshot(CHILD, docs(CHILD, ROOT, streams={n: OLD for n in streams}), body, streams)

    def compare(self, before, after):
        return changes.compare(dict(object_id=CHILD, before=before, after=after))

    def test_whole_body_and_module_diff(self):
        name = CHILD+'.0'
        result = self.compare(self.frame(b'{1,"Old"}', {name: b'old\n'}),
                              self.frame(b'{1,"New"}', {name: b'new\n'}))
        self.assertEqual([r['name'] for r in result['streams']], ['$body', name])
        row = result['streams'][1]
        self.assertIn('-old\n+new\n', row['diff'])
        self.assertEqual(row['after']['text'], 'new\n')
        self.assertEqual(result['representation'], 'native')

    def test_creation_and_deletion_preserve_binary_and_empty_streams(self):
        blob = b'\x00\xff\x01'
        frame = self.frame(b'', {CHILD+'.0': blob, CHILD+'.1': b''})
        for before, after, action, side in [(None, frame, 'create', 'after'), (frame, None, 'delete', 'before')]:
            result = self.compare(before, after)
            self.assertEqual(result['action'], action)
            self.assertEqual(len(result['streams']), 3)
            row = next(r for r in result['streams'] if r['name'] == CHILD+'.0')
            self.assertEqual(row[side]['format'], 'binary')
            self.assertEqual(base64.b64decode(row[side]['data']), blob)
            self.assertNotIn('diff', row)

    def test_identical_snapshots_and_stream_add_remove(self):
        frame = self.frame()
        self.assertFalse(self.compare(frame, frame)['content_changed'])
        result = self.compare(self.frame(streams={CHILD+'.0': b'old'}),
                              self.frame(streams={CHILD+'.1': b'new'}))
        self.assertEqual([r['action'] for r in result['streams']], ['delete', 'create'])

    def test_reject_missing_corrupt_wrong_object_and_incomplete_streams(self):
        incomplete = snapshot(CHILD, docs(CHILD, ROOT, streams={CHILD+'.0': OLD}), b'body')
        for before in [None, 'not base64', incomplete,
                       snapshot(ROOT, docs(ROOT, ROOT), b'wrong')]:
            with self.subTest(before=str(before)[:20]), self.assertRaises((ValueError, KeyError)):
                self.compare(before, None)

    def test_large_text_preserved_but_diff_bounded(self):
        raw = b'a'*(changes.MAX_DIFF_TEXT+1)
        row = self.compare(None, self.frame(raw))['streams'][0]
        self.assertEqual(row['after']['size'], len(raw))
        self.assertEqual(row['diff_omitted'], 'text_size_limit')

    def test_unterminated_lines_do_not_merge_in_diff(self):
        row = self.compare(self.frame(b'before'), self.frame(b'after'))['streams'][0]
        self.assertIn('-before\n\\ No newline at end of file\n+after\n', row['diff'])

    @unittest.skipUnless(OSCRIPT and Path(OSCRIPT).is_file(), 'OneScript unavailable')
    def test_oscript_python_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            before, after = [Path(directory)/name for name in ('before.bin', 'after.bin')]
            before.write_bytes(base64.b64decode(self.frame(b'before')))
            after.write_bytes(base64.b64decode(self.frame(b'after')))
            result = subprocess.run([OSCRIPT, str(PROJECT/'tests/check-object-changes.os'), '--compare',
                                     str(before), str(after), sys.executable], cwd=PROJECT,
                                    capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, (result.stdout+result.stderr).decode('utf-8', errors='replace'))


if __name__ == '__main__':
    unittest.main()
