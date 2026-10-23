"""CommonModule properties and its native info/text external container."""
import struct
import copy
import uuid
import native_metadata as s
import serialization_context as contexts
import packet_builder as packets
import metadata_identifiers as identifiers
import platform_profiles as platforms
import native_content


def module_xml(text, platform='8.5.1.1529'):
    from metadata_object_xml import object_xml
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


def compile_change(request):
    """Replace the sole external source stream of an existing CommonModule."""
    if not platforms.legacy(request['platform']):
        raise ValueError('CommonModule changes require legacy platform profile')
    oid = str(uuid.UUID(request['object_id']))
    frame=contexts.read(request,oid,'Oversized or invalid module input','Module snapshot/context mismatch');saved,docs,data=frame.saved,frame.docs,frame.data;m=frame.metadata
    if (s.val(m[1]) != oid or s.val(m[2]) != identifiers.class_id('CommonModule')
            or s.val(m[4]) != s.ZERO or s.val(m[3]) == s.ZERO
            or s.render(m[12]) != '{0}' or s.render(m[13]) != '{0}'
            or s.render(saved[0][12]) != '{0}' or s.render(saved[0][13]) != '{0}'
            or s.metadata_relations(m[14]) != {s.val(m[3]): 1}
            or s.metadata_relations(saved[0][14]) != s.metadata_relations(m[14])):
        raise ValueError('Expected a flat existing CommonModule')
    name = oid + '.0'; refs = m[11]
    empty_source=s.render(refs)=='{0}'
    if not empty_source and (len(refs) != 3 or s.val(refs[0]) != '1' or s.val(refs[1]) != name):
        raise ValueError('Expected the sole module source external stream')
    if not empty_source:uuid.UUID(s.val(refs[2]))
    externals = docs[2]
    if empty_source:
        if s.render(externals)!='{0}' or s.render(saved[2])!='{0}':raise ValueError('Unsupported empty module external context')
    elif (len(externals) != 2 or s.val(externals[0]) != '1' or len(externals[1]) != 3
            or s.val(externals[1][0]) != name or s.val(externals[1][1]) != s.val(refs[2])
            or s.val(externals[1][2]) != '1' or s.render(saved[2]) != '{0}'):
        raise ValueError('Unsupported module external context')
    original=contexts.original_version(request['original_version'],m,'Source module version mismatch')
    raw = s.inflate(data)
    body = s.Parser(raw.decode('utf-8-sig')).documents()
    if (len(body) != 1 or len(body[0]) != 3 or s.val(body[0][0]) != '1'
            or len(body[0][1]) != 10 or s.val(body[0][1][0]) != '12'):
        raise ValueError('Unsupported module body layout')
    common = body[0][1][1]
    if (len(common) != 9 or s.val(common[0]) != '3' or len(common[1]) != 3
            or s.val(common[1][2]) != oid or s.val(common[2]) != s.val(m[9])):
        raise ValueError('Module body/description mismatch')
    import metadata_object_xml
    xml=request.get('object_xml')
    if xml is None:
        import xml_namespaces
        xml=xml_namespaces.serialize(metadata_object_xml.export(body[0],{},request['platform'],'CommonModule'))
    raw,_=metadata_object_xml.change(xml,request['platform'],'CommonModule',body[0],allow_rename=request.get('_allow_rename',False))
    m[9]=copy.deepcopy(s.Parser(raw.decode('utf-8-sig')).documents()[0][1][1][2])
    if request.get('preserve_content'):
        if request.get('clear_module_text') and (not empty_source or request.get('source_text')!=''):raise ValueError('Cannot preserve and clear a module stream')
        return native_content.body_change(docs,saved,raw,oid)
    if request.get('clear_module_text'):
        if request.get('source_text')!='':raise ValueError('Cleared CommonModule must have empty source text')
        return native_content.external_change(docs,saved,raw,name,None,None)
    external_data = s.compress(module_container(request['source_text']))
    return native_content.external_change(docs, saved, raw, name, external_data, packets.external_version())


def serialize_change(request):
    if request.get('clear_module_text'):raise ValueError('Use complete-export preparation to remove a CommonModule source stream')
    return packets.pack_external_change(compile_change(request), request['original_version'].lower())


def main():
    from serializer_cli import run
    run(serialize_change)


if __name__ == '__main__': main()
