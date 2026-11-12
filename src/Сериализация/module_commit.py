"""Compile one existing Module stream from a complete addressed snapshot.

ibcmd owns the BSL representation. A temporary CF fragment contains just that
stream and a versions table; it is never treated as a complete configuration.
No repository calls, source edits, captures or commit transport live here.
"""
import base64
import copy
import hashlib
import io
from pathlib import PurePosixPath
import re
import uuid

import cf_container
import configuration_commit
import external_data
import export_coverage
import ibcmd_backend
import metadata_context
import metadata_identifiers
import native_content
import native_metadata as s
import native_streams
import object_changes
import packet_builder
import platform_profiles
import repository_cache
import serialization_context
import resource_limits as limits

MAX_MODULE_BYTES = 8 * 1024 * 1024


def text(value):
    if not isinstance(value, str) or '\0' in value or len(value.encode('utf-8')) > limits.get('module_bytes',MAX_MODULE_BYTES):
        raise ValueError('Expected BSL text within module byte limit without NUL')
    return value


def route(kind, path):
    if (not isinstance(path, str) or '\\' in path or PurePosixPath(path).is_absolute()
            or str(PurePosixPath(path)) != path or '..' in PurePosixPath(path).parts):
        raise ValueError('Expected an exact relative module route')
    rows = [row for row in native_streams.routes(kind).values()
            if row['path'] == path and row['codec'] == 'Module']
    if len(rows) != 1:
        raise ValueError('Unsupported standalone Module route: ' + path)
    return rows[0]


def read_source(request):
    oid = metadata_context.guid(request['object_id'])
    platform_profiles.version_parts(request['platform'])
    if not platform_profiles.legacy(request['platform']):
        raise ValueError('Module preparation requires legacy profile')
    metadata_context.guid(request['repository_version'])
    if not isinstance(request['repository'], str) or not request['repository']:
        raise ValueError('Missing repository identity')
    raw = s.decode_storage(request['snapshot'])
    s.validate_storage(raw)
    payloads, manifest = external_data.records(raw)
    if s.val(manifest[1]) != '1':
        raise ValueError('Module preparation requires exactly one snapshot object')
    record = external_data.extract(raw, oid)  # Includes every declared external.
    saved = s.Parser(payloads[s.val(manifest[3])].decode('utf-8-sig')).documents()
    if len(saved) != 3 or len(saved[0]) != 17:
        raise ValueError('Invalid snapshot metadata documents')
    m = saved[0]
    source = request['source']
    original = serialization_context.original_version(source['original'], m)
    local = source['local']
    if (not isinstance(local, str) or not re.fullmatch('[0-9a-f]{40}', local)
            or uuid.UUID(s.val(m[8])).bytes_le.hex() != local[:32]):
        raise ValueError('Source local version mismatch')
    expected = packet_builder.description(m, bytes.fromhex(original), bytes.fromhex(local))
    expected.update(version_number=int(s.val(m[5])), self_version_number=int(s.val(m[6])))
    if source != expected:
        raise ValueError('Snapshot does not match source descriptor')
    kind = metadata_identifiers.class_labels().get(record['class_id'])
    if kind is None:
        raise ValueError('Unknown object class for Module route')
    selected = route(kind, request['module_path'])
    name = oid + selected['suffix']
    versions = serialization_context.external_versions(m[11])
    if native_streams.select(m, versions) != set(versions) or name not in versions:
        raise ValueError('Module route is absent or snapshot streams have invalid owners')
    metadata_context.children(m)
    s.metadata_relations(m[14])
    streams = {entry['name']: s.inflate(base64.b64decode(entry['data'], validate=True))
               for entry in record['externals']}
    body_packed = base64.b64decode(record['data'], validate=True)
    return oid, kind, saved, body_packed, streams, name, versions


def module_companions(raw):
    """Read-only proof: protected/compound module companions cannot change."""
    if raw.startswith(b'\xef\xbb\xbf'):
        return {}
    stream = io.BytesIO(raw)
    container = cf_container.detect_format(stream)
    container.read(stream)
    if 'text' not in container.files:
        raise ValueError('Protected module has no editable text')
    return {name: b''.join(entry.data) for name, entry in container.files.items() if name != 'text'}


def fragment(name, raw, version):
    values = {'': str(uuid.uuid4()), name: version, 'versions': str(uuid.uuid4())}
    atoms = [s.atom(1), s.atom(len(values))]
    for key, value in sorted(values.items()):
        atoms.extend([s.atom(key, True), s.atom(value)])
    return {name: raw, 'versions': s.text_bytes([atoms])}


def verify_fragment(before, after, name, target):
    if set(after) != set(before):
        raise ValueError('Compiler changed fragment member set')
    version_names = set(repository_cache.versions(after['versions']))
    if version_names != {name, 'versions', ''}:
        raise ValueError('Compiler changed fragment versions member set')
    if export_coverage._module(after[name]) != target:
        raise ValueError('Compiled module readback differs from requested BSL')
    if module_companions(before[name]) != module_companions(after[name]):
        raise ValueError('Compiler changed non-text module companions')


def prepare(request):
    target = text(request['module_text'])
    oid, kind, saved, body_packed, streams, name, versions = read_source(request)
    source_text = export_coverage._module(streams[name])
    if source_text is None:
        raise ValueError('Protected or unsupported source module representation')
    text(source_text)
    expected_hash = request.get('expected_source_sha256')
    if expected_hash is not None and (not isinstance(expected_hash, str)
            or not re.fullmatch('[0-9a-f]{64}', expected_hash)
            or hashlib.sha256(source_text.encode('utf-8')).hexdigest() != expected_hash):
        raise ValueError('Source module hash differs from expected baseline')
    options = request.get('compiler')
    if (not isinstance(options, dict) or set(options) != {'backend', 'executable'}
            or options['backend'] != 'ibcmd'):
        raise ValueError('Module compiler requires backend=ibcmd and executable; no base CF')
    digest = lambda value: hashlib.sha256(value).hexdigest()
    compiler_platform = '.'.join(request['platform'].split('.')[:3])
    review = dict(object_id=oid, kind=kind, module_path=request['module_path'], stream=name,
                  repository=request['repository'], platform=request['platform'], repository_version=request['repository_version'],
                  source=request['source'], source_snapshot_sha256=digest(s.decode_storage(request['snapshot'])),
                  body_sha256=digest(s.inflate(body_packed)),
                  before_sha256=digest(source_text.encode('utf-8')), after_sha256=digest(target.encode('utf-8')),
                  diff=object_changes.text_diff(source_text, target, request['module_path']),
                  captured=False, committed=False, compiler='ibcmd', compiler_platform=compiler_platform, has_changes=source_text != target)
    if source_text == target:
        return dict(has_changes=False, review=review)
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory(prefix='crs-module-') as temporary:
        work = Path(temporary)
        base, output, source = work/'fragment.cf', work/'changed.cf', work/'module.bsl'
        image = fragment(name, streams[name], versions[name])
        ibcmd_backend.write_fragment(base, image)
        source.write_bytes(target.encode('utf-8-sig'))
        with ibcmd_backend.Compiler(dict(compiler=dict(options, base_cf=str(base)))) as compiler:
            compiler.execute('cf', 'overlay', base, output, '--platform', compiler_platform, '--module', name+'='+str(source))
        after = ibcmd_backend.read_fragment(output)
        verify_fragment(image, after, name, target)
    body = s.inflate(body_packed)
    docs = copy.deepcopy(saved)
    content = native_content.compiled_stream_changes(docs, saved, body, oid, streams,
                                                    dict(streams, **{name: after[name]}), {name})
    for index in (9, 10, 12, 13, 14, 15, 16):
        if s.render(content.docs[0][index]) != s.render(saved[0][index]):
            raise ValueError('Module compilation changed object metadata or graph')
    original = bytes.fromhex(request['source']['original'])
    local = packet_builder.content_version(body)
    packet_builder.commit_metadata(docs[0], original, local)
    desc = packet_builder.description(docs[0], original, local)
    graph = configuration_commit.final_graph({oid: saved}, {oid: docs}, [oid], set())
    packet = packet_builder.assemble(graph, [packet_builder.ObjectRecord(oid, s.text_bytes(docs), body_packed, content.streams)])
    review.update(changed_streams=[name], preserved_streams=[key for key in sorted(streams) if key != name],
                  packet_sha256=digest(packet))
    return dict(has_changes=True, review=review, data=base64.b64encode(packet).decode(),
                descriptions=[desc], requested=[desc], changed_ids=[oid], new_ids=[], removed_ids=[],
                version_code='', version_code_resolved=False,
                verification=[dict(id=oid,body_sha256=digest(body),streams=[dict(name=key,sha256=digest(value)) for key,value in dict(streams,**{name:after[name]}).items()])],
                externals=[dict(object_id=oid, **entry) for entry in content.externals],
                repository=request['repository'], platform=request['platform'], repository_version=request['repository_version'])


if __name__ == '__main__':
    from serializer_cli import run
    run(prepare)
