"""Read upstream-produced CF fixtures and preserve native protocol text."""
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'Сериализация'))
import cf_container as cf
import ibcmd_backend as backend
import native_metadata as s


class ContainerTests(unittest.TestCase):
    def test_large_index_chain_ends_at_the_last_data_block(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'many.cf'
            image={str(index):('value '+str(index)).encode() for index in range(500)}
            image.update(root=b'root',version=b'version',versions=b'versions')
            backend.write_cf(path,image)
            self.assertEqual(backend.read_cf(path),image)
            with path.open('rb') as source:
                container=cf.detect_format(source);container.read_header(source)
                doc=cf.Document(container);block=doc.read_block(source,container.header_size)
                left=block.doc_size-len(block.data);count=1
                while left:
                    block=doc.read_block(source,block.next_block_offset,left)
                    left-=len(block.data);count+=1
                self.assertGreater(count,1)
                self.assertEqual(block.next_block_offset,container.end_marker)

    def test_upstream_format15_and_format16_images_and_local_repacking(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures' / 'cf_containers.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.cf'
            normalized = Path(directory) / 'normalized.cf'
            for case in fixture['cases']:
                with self.subTest(format=case['format']):
                    path.write_bytes(zlib.decompress(base64.b64decode(case['container_zlib'])))
                    expected = json.loads(zlib.decompress(base64.b64decode(case['members_zlib'])))
                    expected = {name: base64.b64decode(raw) for name, raw in expected.items()}
                    self.assertEqual(backend.read_cf(path), expected)
                    backend.write_cf(normalized, expected)
                    self.assertEqual(backend.read_cf(normalized), expected)

    def test_document_chain_reads_continuations_and_rejects_cycles_and_truncation(self):
        for container_class in (cf.Container, cf.Container64):
            for next_offset, payload, succeeds in ((200, b'def', True), (16, b'def', False), (200, b'd', False)):
                with self.subTest(format=container_class.__name__, next_offset=next_offset, payload=payload):
                    container = container_class()
                    container.file = io.BytesIO(b'\0' * 300)
                    doc = cf.Document(container)
                    doc.write_block(io.BytesIO(b'abc'), doc_size=6, offset=container.header_size,
                                    next_block_offset=next_offset)
                    doc.write_block(io.BytesIO(payload), doc_size=0, offset=200,
                                    next_block_offset=container.header_size)
                    if succeeds:
                        self.assertEqual(doc.read(container.file, container.header_size), b'abcdef')
                    else:
                        with self.assertRaises(ValueError):
                            doc.read(container.file, container.header_size)

    def test_truncated_and_invalid_block_headers_are_rejected(self):
        for data in (b'\0' * 16, b'\0' * 80):
            with self.subTest(data=len(data)), self.assertRaises(ValueError):
                cf.Document(cf.Container()).read(io.BytesIO(data), 16)

    def test_native_text_keeps_quotes_base64_linebreaks_and_nested_groups(self):
        long_text = ('Текст "модуля", {данные}\r\n' * 100)
        binary = '#base64:' + 'A' * 72 + '\r\n' + 'B' * 64
        docs = [[s.atom(1), [s.atom(long_text, True), s.atom(binary)], []], [s.atom(0)]]
        expected = '\ufeff{1,\r\n{' + s.render(s.atom(long_text, True)) + ',' + binary + '},\r\n{}\r\n},{0}'
        self.assertEqual(s.native_body_bytes(docs), expected.encode('utf-8'))
        self.assertEqual(s.render(s.Parser(expected.lstrip('\ufeff')).documents()[0]), s.render(docs[0]))


if __name__ == '__main__':
    unittest.main()
