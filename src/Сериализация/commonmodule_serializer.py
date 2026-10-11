"""CommonModule properties and its native info/text external container."""
import struct
import comment_serializer as s


def module_xml(text, platform='8.5.1.1529'):
    from flat_object_serializer import object_xml
    return object_xml(text, platform, 'CommonModule')


def module_container(source):
    if not isinstance(source, str) or '\0' in source:
        raise ValueError('Invalid module source text')
    source = source.removeprefix('\ufeff').replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')
    encoded = b'\xef\xbb\xbf' + source.encode('utf-8')
    if len(encoded) > 8 * 1024 * 1024:
        raise ValueError('Oversized module source text')
    files = [('info', b'\xef\xbb\xbf{3,1,0,"",0}'), ('text', encoded)]
    marker = 0x7fffffff

    def block(data, minimum=0):
        size = max(len(data), minimum)
        return ('\r\n%08x %08x %08x \r\n' % (len(data), size, marker)).encode('ascii') + data + bytes(size - len(data))

    # 16-byte header, 31-byte table block header, two 12-byte entries.
    content = bytearray(struct.pack('<IIII', marker, 512, 2, 0) + bytes(31 + 24))
    entries = []
    for name, data in files:
        attribute = bytes(20) + name.encode('utf-16le') + bytes(4)
        attr_pos = len(content)
        content += block(attribute)
        data_pos = len(content)
        content += block(data, 512)
        entries.append(struct.pack('<III', attr_pos, data_pos, marker))
    content[16:71] = block(b''.join(entries))
    return bytes(content)
