"""CommonModule properties and its native info/text external container."""
import copy
import json
import struct
import uuid
import metadata_serializer as s
import serialization_context as contexts
import packet_builder as packets
import metadata_identifiers as identifiers
import platform_profiles as platforms


def module_xml(text, platform='8.5.1.1529'):
    from flat_object_serializer import object_xml
    return object_xml(text, platform, 'CommonModule')


def module_xml_from_native(common):
    """Complete XML input for the compatibility source-only operation."""
    import xml.etree.ElementTree as E
    from pathlib import Path
    import constant_serializer as c
    q='{'+c.MD+'}'
    top=E.Element(q+'MetaDataObject',version='2.21');obj=E.SubElement(top,q+'CommonModule',uuid=s.val(common[1][2]))
    props=E.SubElement(obj,q+'Properties');E.SubElement(props,q+'Name').text=s.val(common[2])
    synonym=E.SubElement(props,q+'Synonym')
    for lang,content in s.synonym_value(common[3]):
        item=E.SubElement(synonym,'{'+c.CORE+'}item')
        E.SubElement(item,'{'+c.CORE+'}lang').text=lang;E.SubElement(item,'{'+c.CORE+'}content').text=content
    E.SubElement(props,q+'Comment').text=s.val(common[4])
    layout=json.loads(Path(__file__).with_name('commonmodule_layout_851.json').read_text(encoding='utf-8'))
    for key,value in layout['defaults'].items():E.SubElement(props,q+key).text=value
    return E.tostring(top,encoding='unicode')


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


def serialize_change(request):
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
    if len(refs) != 3 or s.val(refs[0]) != '1' or s.val(refs[1]) != name:
        raise ValueError('Expected the sole module source external stream')
    uuid.UUID(s.val(refs[2]))
    externals = docs[2]
    if (len(externals) != 2 or s.val(externals[0]) != '1' or len(externals[1]) != 3
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
    xml_id,xml_name,new_raw,_=module_xml(request.get('object_xml',module_xml_from_native(common)),request['platform'])
    if xml_id!=oid or xml_name!=s.val(m[9]):raise ValueError('CommonModule UUID or name mismatch; rename is unsupported')
    baseline=s.Parser(new_raw.decode('utf-8-sig')).documents()
    baseline[0][1][1]=copy.deepcopy(common)
    if s.render(baseline)!=s.render(body):raise ValueError('Source CommonModule properties are outside the verified XML profile')
    raw=new_raw;data=s.compress(raw)
    external_data = s.compress(module_container(request['source_text']))
    return packets.pack_external_change(docs, saved, data, oid, name, original, raw, external_data)


def main():
    from serializer_cli import run
    run(serialize_change)


if __name__ == '__main__': main()
