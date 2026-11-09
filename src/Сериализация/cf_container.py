"""CF Format15/Format16 containers; no XML/object-property conversion.

Adapted subset of v8unpack 1.2.13 container.py/container_doc.py (MIT).
Upstream: https://github.com/saby-integration/v8unpack
Copyright (c) 2015 infactum. See V8UNPACK-LICENSE.txt beside this module.
Only in-memory record I/O is retained; no extraction CLI or dependencies.
"""
import collections
import io
import math
import os
import tempfile
from datetime import datetime, timedelta
from struct import pack, unpack, calcsize

Header = collections.namedtuple('Header', 'first_empty_block_offset default_block_size count_files')
Block = collections.namedtuple('Block', 'doc_size current_block_size next_block_offset data')
File = collections.namedtuple('File', 'name size created modified data')
BUFFER_CHUNK_SIZE = 512


def file_size(file):
    position = file.tell()
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(position)
    return size


def epoch2int(epoch_time):
    return (datetime.fromtimestamp(epoch_time) - datetime(1, 1, 1)) // timedelta(microseconds=100)


def detect_format(file, offset=0):
    file.seek(offset)
    first = file.read(8)
    if not first:
        raise EOFError('Missing CF container')
    return Container() if first[:4] == b'\xff\xff\xff\x7f' else Container64()


class Container:
    end_marker = 2147483647
    header_fmt = '<4i'
    header_size = 16
    block_header_fmt = '2s8s1s8s1s8s1s2s'
    block_header_size = 31
    block_header_fmt_size = 8
    index_fmt = 'i'
    default_block_size = 512
    index_block_size = 512

    def __init__(self):
        self.file = None
        self.offset = 0
        self.first_empty_block_offset = None
        self.default_block_size = 512
        self.files = None
        self.size = 0
        self.toc = []

    def read(self, file, offset=0):
        self.offset = offset
        self.size = 0
        header = self.read_header(file)
        block = header.default_block_size
        if block <= 0 or block > 65536 or block & (block - 1):
            raise ValueError('Invalid CF default block size')
        self.file = file
        self.first_empty_block_offset = header.first_empty_block_offset
        self.default_block_size = header.default_block_size
        self.files = self.read_files(self.file)

    def read_header(self, file):
        file.seek(0 + self.offset)
        buff = file.read(calcsize(self.header_fmt))
        if len(buff) != calcsize(self.header_fmt):
            raise ValueError('Truncated CF container header')
        header = unpack(self.header_fmt, buff)
        return Header(header[0], header[1], header[2])

    @classmethod
    def parse_datetime(cls, time):
        try:
            return datetime(1, 1, 1) + timedelta(microseconds=time * 100)
        except OverflowError:
            return datetime(9999, 12, 31, 23, 59, 59)

    def read_files(self, file):
        doc = Document(self)
        doc_data = doc.read(file, self.header_size, self.index_block_size)
        row_size = calcsize('<3' + self.index_fmt)
        if len(doc_data) % row_size:
            raise ValueError('Invalid CF table of contents')
        table_of_contents = []
        for pos in range(0, len(doc_data), row_size):
            description, data, marker = unpack('<3' + self.index_fmt, doc_data[pos:pos + row_size])
            if marker != self.end_marker:
                raise ValueError('Invalid CF table marker')
            table_of_contents.append((description, data))
        self.size += self.header_size + doc.full_size
        files = collections.OrderedDict()
        for (file_description_offset, file_data_offset) in table_of_contents:
            doc = Document(self)
            doc_data = doc.read(file, file_description_offset)
            self.size += doc.full_size
            if len(doc_data) < 20:
                raise ValueError('Truncated CF file description')
            fmt = '<QQi' + str(len(doc_data) - 20) + 's'
            file_description = unpack(fmt, doc_data)
            name = file_description[3].decode('utf-16-le').partition('\x00')[0]
            if not name or name in files:
                raise ValueError('Empty or duplicate CF member name')
            doc = Document(self)
            file_data = doc.read_chunk(file, file_data_offset, self.default_block_size)
            self.size += doc.full_size
            inner_file = File(name, doc.data_size, self.parse_datetime(file_description[0]), self.parse_datetime(file_description[1]), file_data)
            files[inner_file.name] = inner_file
        return files

    def write_header(self, count_files=0):
        self.file.seek(self.offset)
        self.file.write(pack(self.header_fmt, self.end_marker, self.default_block_size, count_files, 0))
        self.file.write(b'\x00' * (self.index_block_size + self.block_header_size))

    def write_table_off_content(self):
        if len(self.toc) == 0:
            raise IOError('Container is empty')
        with tempfile.TemporaryFile() as f:
            for (attr_offset, data_offset) in self.toc:
                f.write(pack(f'<3{self.index_fmt}', attr_offset, data_offset, self.end_marker))
            doc_size = file_size(f)
            total_blocks = math.ceil(doc_size / self.index_block_size)
            doc = Document(self)
            if total_blocks == 1:
                doc.write_block(f, doc_size=doc_size, offset=self.header_size)
            else:
                f.seek(0)
                next_block_offset = file_size(self.file)
                doc.write_block(io.BytesIO(f.read(self.index_block_size)), doc_size=doc_size, offset=self.header_size, min_block_size=self.index_block_size, next_block_offset=next_block_offset)
                self.file.seek(0, os.SEEK_END)
                for i in range(1, total_blocks):
                    next_block_offset += self.index_block_size + self.block_header_size
                    following = next_block_offset if i < total_blocks - 1 else self.end_marker
                    doc.write_block(io.BytesIO(f.read(self.index_block_size)), doc_size=0, next_block_offset=following, min_block_size=self.index_block_size)

    def add_file(self, fd, name, inflate=False):
        doc = Document(self)
        attribute_doc_offset = doc.write_header(fd, name)
        doc = Document(self)
        if inflate:
            raise ValueError('CF writer expects already compressed records')
        else:
            data_doc_offset = doc.write(fd, min_block_size=self.default_block_size)
        self.toc.append((attribute_doc_offset, data_doc_offset))

    @staticmethod
    def int2hex(value):
        return f'{value:02x}'.rjust(8, '0')

class Container64(Container):
    end_marker = 18446744073709551615
    header_fmt = '<Q3i'
    header_size = 20
    block_header_fmt = '2s16s1s16s1s16s1s2s'
    block_header_fmt_size = 16
    block_header_size = 55
    index_fmt = 'Q'
    index_block_size = 65536

    @staticmethod
    def int2hex(value):
        return f'{value:02x}'.rjust(16, '0').upper()

class Document:

    def __init__(self, container):
        self.container = container
        self.full_size = 0
        self.data_size = 0

    def read(self, file, offset, min_block_size=0):
        document_data = self.read_chunk(file, offset, min_block_size)
        return b''.join([chunk for chunk in document_data])

    def read_chunk(self, file, offset, min_block_size=0):
        gen = self._read_gen(file, offset, min_block_size)
        try:
            self.data_size = next(gen)
        except StopIteration:
            self.data_size = 0
        return gen

    def _read_gen(self, file, offset, min_block_size=0):
        header_block = self.read_block(file, offset)
        doc_size = max(header_block.doc_size, min_block_size)
        if doc_size > header_block.current_block_size:
            self.full_size = doc_size + math.ceil(header_block.doc_size / header_block.current_block_size) * min_block_size
            if min_block_size == self.container.index_block_size:
                self.full_size += self.container.index_block_size
        else:
            self.full_size = doc_size + self.container.block_header_size
        yield header_block.doc_size
        yield header_block.data
        left_bytes = header_block.doc_size - len(header_block.data)
        next_block_offset = header_block.next_block_offset
        seen = {offset}
        while left_bytes > 0:
            if next_block_offset == self.container.end_marker or next_block_offset in seen:
                raise ValueError('Truncated or cyclic CF document chain')
            seen.add(next_block_offset)
            block = self.read_block(file, next_block_offset, left_bytes)
            left_bytes -= len(block.data)
            yield block.data
            next_block_offset = block.next_block_offset

    def read_block(self, file, offset, max_data_length=None):
        if offset < self.container.header_size:
            raise ValueError('Invalid CF block offset')
        file.seek(offset + self.container.offset)
        header_size = self.container.block_header_size
        buff = file.read(header_size)
        if len(buff) != header_size:
            raise ValueError('Truncated CF block header')
        header = unpack(self.container.block_header_fmt, buff)
        if (header[0], header[2], header[4], header[6], header[7]) != (b'\r\n', b' ', b' ', b' ', b'\r\n'):
            raise ValueError('Invalid CF block header')
        doc_size = int(header[1], 16)
        current_block_size = int(header[3], 16)
        next_block_offset = int(header[5], 16)
        if current_block_size <= 0 or doc_size > file_size(file) or current_block_size > file_size(file):
            raise ValueError('Invalid CF block size')
        if max_data_length is None:
            max_data_length = min(current_block_size, doc_size)
        data_size = min(current_block_size, max_data_length)
        data = file.read(data_size)
        if len(data) != data_size:
            raise ValueError('Truncated CF block data')
        return Block(doc_size, current_block_size, next_block_offset, data)

    def write_header(self, file, file_name):
        modify_time = epoch2int(os.stat(file.fileno()).st_mtime)
        creation_time = epoch2int(os.stat(file.fileno()).st_ctime)
        buffer = b''.join([pack('<QQi', creation_time, modify_time, 0), file_name.encode('utf-16-le'), b'\x00' * 4])
        attribute_doc_offset = self.write(io.BytesIO(buffer))
        return attribute_doc_offset

    def write(self, data, *, min_block_size=0):
        return self.write_block(data, doc_size=file_size(data), min_block_size=min_block_size)

    def write_block(self, data, *, doc_size=0, min_block_size=0, offset=None, next_block_offset=None):
        if offset is not None:
            self.container.file.seek(offset)
        else:
            offset = file_size(self.container.file)
        block_size = file_size(data)
        min_block_size = max(min_block_size, block_size)
        if not next_block_offset:
            next_block_offset = self.container.end_marker
        header_data = ('\r\n', self.container.int2hex(doc_size), ' ', self.container.int2hex(min_block_size), ' ', self.container.int2hex(next_block_offset), ' ', '\r\n')
        header = pack(self.container.block_header_fmt, *[x.encode() for x in header_data])
        self.container.file.write(header)
        self.write_block_data(data, self.container.file)
        self.container.file.write(b'\x00' * (min_block_size - data.tell()))
        return offset

    @staticmethod
    def write_block_data(data, dest_file):
        data.seek(0)
        while True:
            buffer = data.read(BUFFER_CHUNK_SIZE)
            if not buffer:
                break
            dest_file.write(buffer)
