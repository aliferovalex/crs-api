"""Build a Configuration root change packet from full XML and current snapshots."""
import base64
import copy
import re
import uuid
import xml.etree.ElementTree as ET
import platform_profiles as platforms
from native_metadata import HEADER, MAX_BYTES, Parser, ZERO, atom, compress, inflate, read_record, render, text_bytes, val, validate_storage
from configuration_xml import ROOT_CLASS, ROOT_FEATURE_CLASS, common_properties, configuration_baseline_from_snapshot, configuration_xml_values, xml_property_patches
from metadata_context import context_metadata


def serialize(request):
    import packet_builder as packets
    platforms.profile(request['platform'])
    mode = request.get('mode', 'comment')
    if mode not in ('comment', 'properties'):
        raise ValueError('Unsupported serialization mode')
    allowed = ('Comment',) if mode == 'comment' else None
    for key in ('snapshot', 'context', 'after_xml'):
        if not isinstance(request[key], str) or len(request[key]) > MAX_BYTES * 2:
            raise ValueError("Oversized or invalid serializer input")
    snapshot = base64.b64decode(request["snapshot"], validate=True)
    context = base64.b64decode(request["context"], validate=True)
    validate_storage(snapshot)
    validate_storage(context)
    object_id = str(uuid.UUID(request["object_id"]))
    if snapshot[:12] != HEADER or len(snapshot) > MAX_BYTES:
        raise ValueError("Unsupported snapshot")
    old_meta_bytes, pos = read_record(snapshot, 12)
    old_data, pos = read_record(snapshot, pos)
    old_meta = Parser(old_meta_bytes.decode("utf-8-sig")).documents()
    meta = context_metadata(context, object_id)
    m, saved = meta[0], old_meta[0]
    if len(meta) != 3 or len(old_meta) != 3 or val(m[0]) != "5" or val(saved[0]) != "5":
        raise ValueError("Unsupported metadata format")
    if len(m) != 17 or len(saved) != 17 or val(m[1]).lower() != object_id or val(saved[1]).lower() != object_id:
        raise ValueError("Unsupported object metadata")
    if val(m[2]) != ROOT_CLASS or val(m[3]) != ZERO or val(m[4]) != ZERO:
        raise ValueError("Only an existing Configuration root is supported")
    if [val(m[i]) for i in (2, 5, 6, 7, 8)] != [val(saved[i]) for i in (2, 5, 6, 7, 8)]:
        raise ValueError("Snapshot and updateInfo context versions differ")
    if render(m[11]) != "{0}" or render(meta[2]) != "{0}":
        raise ValueError("External object changes are unsupported")
    original = request["original_version"].lower()
    if not re.fullmatch("[0-9a-f]{40}", original) or uuid.UUID(val(m[7])).bytes_le.hex() != original[:32]:
        raise ValueError("Source version mismatch")
    original_raw = inflate(old_data)
    if not original_raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Unsupported object text encoding")
    text = original_raw.decode("utf-8-sig")
    documents = Parser(text).documents()
    common = common_properties(documents, object_id, request['platform'])
    before_xml = request.get('before_xml')
    if before_xml is None:
        before_xml = configuration_baseline_from_snapshot(request['after_xml'], object_id, common, documents, request['platform'], request['context'])
    if not isinstance(before_xml, str) or len(before_xml) > MAX_BYTES * 2:
        raise ValueError('Oversized or invalid baseline XML')
    if platforms.legacy(request['platform']) and request.get('before_xml') is not None:
        if '<!DOCTYPE' in before_xml.upper():
            raise ValueError('DOCTYPE is unsupported')
        before_root = ET.fromstring(before_xml)
        refs = []
        for contained in before_root.iter():
            if contained.tag.rsplit('}', 1)[-1] == 'ContainedObject':
                fields = {e.tag.rsplit('}', 1)[-1]: e.text for e in contained}
                if fields.get('ClassId', '').lower() == ROOT_FEATURE_CLASS:
                    refs.append(fields.get('ObjectId', '').lower())
        if refs != [val(common[1][2]).lower()]:
            raise ValueError('XML common properties UUID does not match native body')
    xml_property_patches(before_xml, request['after_xml'], object_id, common, documents, request['platform'], allowed)
    patches = configuration_xml_values(request['after_xml'], object_id, common, documents, request['platform'], allowed)
    new_text = text
    for start, end, replacement in sorted(patches, reverse=True):
        new_text = new_text[:start] + replacement + new_text[end:]
    new_raw = b"\xef\xbb\xbf" + new_text.encode("utf-8")
    new_data = compress(new_raw)
    # Experimental client version; this does not reproduce the native hash algorithm.
    version_bytes = packets.content_version(new_raw)
    packets.commit_metadata(m, bytes.fromhex(original), version_bytes)
    m[15:17] = copy.deepcopy(saved[15:17])
    new_meta = text_bytes(meta)
    features = copy.deepcopy(m[13])
    children = []
    for group in (m[12], m[13]):
        if not isinstance(group, list) or not group or int(val(group[0])) != len(group) - 1:
            raise ValueError("Invalid metadata group count")
    if not isinstance(m[14], list) or not m[14] or int(val(m[14][0])) * 2 != len(m[14]) - 1:
        raise ValueError("Invalid metadata relation count")
    for group in m[12][1:]:
        if len(group) < 2 or int(val(group[1])) != len(group) - 2:
            raise ValueError("Invalid child class map")
        children.extend([[copy.deepcopy(child), copy.deepcopy(group[0])] for child in group[2:]])
    child_types = [atom(len(children))]
    for pair in children:
        child_types.extend(pair)
    graph = packets.change_graph(m, child_types, features)
    payload = packets.assemble(graph, [packets.ObjectRecord(object_id, new_meta, new_data)])
    xml = packets.request_xml(request, payload, {object_id: meta}, {object_id: bytes.fromhex(original)}, {object_id: version_bytes})
    return xml, new_raw


def main():
    # All paths and object data arrive through JSON, never shell interpolation.
    from serializer_cli import run
    run(lambda request: {"request_xml": serialize(request)[0]})


if __name__ == "__main__":
    main()
