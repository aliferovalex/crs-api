"""Selected-object XML export through ibcmd-rs; no native property decoder."""
import base64
import json
from pathlib import Path
import re
import subprocess
import tempfile
import uuid
from xml.etree import ElementTree as E

import external_data
import metadata_identifiers
import native_metadata as s
import object_changes
import repository_cache
import object_view_context


class ExportUnavailable(ValueError):
    pass


def rows(encoded_snapshots, oid):
    image, records, metadata = {}, {}, {}
    for encoded in encoded_snapshots:
        packed = s.decode_storage(encoded)
        raw, _ = s.read_record(packed, 12)
        m = s.Parser(raw.decode('utf-8-sig')).documents()[0]
        key = str(uuid.UUID(s.val(m[1])))
        row = external_data.extract(packed, key)
        if key in metadata:
            raise ValueError('Duplicate context object')
        metadata[key] = m
        image[key] = s.inflate(base64.b64decode(row['data'], validate=True))
        refs = {s.val(m[11][i]): s.val(m[11][i+1]) for i in range(1, len(m[11]), 2)}
        records[key] = dict(local=s.val(m[8]), externals=refs)
        for stream in row['externals']:
            if stream['name'] in image:
                raise ValueError('Duplicate context stream')
            image[stream['name']] = s.inflate(base64.b64decode(stream['data'], validate=True))
    if oid not in metadata:
        raise ValueError('Selected snapshot missing from context')
    roots = [key for key, m in metadata.items() if s.val(m[3]) == s.ZERO]
    if len(roots) != 1:
        raise ExportUnavailable('Selected export requires one configuration root snapshot')
    root = roots[0]
    labels = metadata_identifiers.class_labels()
    visited = set()
    def full_name(key):
        if key in visited:
            raise ValueError('Cyclic snapshot ownership')
        visited.add(key)
        if key not in metadata:
            raise ExportUnavailable('Missing ancestor snapshot: '+key)
        m = metadata[key]; kind = labels.get(s.val(m[2])); name = s.val(m[9]); parent = s.val(m[3])
        if kind is None:
            raise ExportUnavailable('Unknown metadata class: '+s.val(m[2]))
        if key == root:
            if kind != 'Configuration': raise ValueError('Root snapshot is not Configuration')
            return 'Configuration'
        if not re.fullmatch(r'[^\W\d]\w{0,79}', name, re.UNICODE):
            raise ValueError('Invalid object name in snapshot')
        owner = full_name(parent)
        if owner == 'Configuration': return kind+'.'+name
        if kind.endswith('Form'): kind = 'Form'
        elif kind.endswith('Template'): kind = 'Template'
        return owner+'.'+kind+'.'+name
    selected = full_name(oid)
    image['root'] = s.text_bytes([[s.atom(2), s.atom(root)]])
    image['version'] = b'{216,0}'
    image['versions'] = repository_cache.service_versions(image, records)
    return image, selected


def export(executable, platform, snapshots, oid, work):
    supplied = snapshots.get('descriptions', {}) if isinstance(snapshots, dict) else {}
    snapshots = snapshots['snapshots'] if isinstance(snapshots, dict) else snapshots
    image, selected = rows(snapshots, oid)
    descriptions = {}
    for encoded in snapshots:
        packed = s.decode_storage(encoded); raw, _ = s.read_record(packed, 12)
        m = s.Parser(raw.decode('utf-8-sig')).documents()[0]
        descriptions[s.val(m[1])] = dict(class_id=s.val(m[2]), parent_id=s.val(m[3]), name=s.val(m[9]))
    for key, value in supplied.items():
        if key in descriptions and descriptions[key] != value: raise ValueError('Context names differ from snapshot metadata')
        descriptions[key] = value
    kind = selected.split('.')[-2] if '.' in selected else selected
    context_plan = object_view_context.plan(image[oid], oid, kind, platform)
    source = work/'rows'; target = work/'xml'; source.mkdir(parents=True)
    for name, raw in image.items():
        # All native names are UUIDs with optional suffixes, or service names.
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..'):
            raise ValueError('Unsafe native row name')
        (source/(name+'__part0.bin')).write_bytes(s.compress(raw))
    # objects export is explicitly a diagnostic/partial converter in ibcmd-rs.
    # Require independent scoped asset coverage before accepting its file map.
    try:
        checked = subprocess.run([str(executable), 'mssql-dump-config', '--rows-dir', str(source),
                                  '--output-dir', str(work/'validation'), '--object', selected,
                                  '--extract-metadata-xml', '--extract-module-text', '--no-binary-rows',
                                  '--platform', platform],
                                 capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise ExportUnavailable('ibcmd selected-object validation timed out') from None
    if checked.returncode:
        raise ExportUnavailable('ibcmd rejected complete source assets: '+
                                (checked.stderr or checked.stdout).decode('utf-8', errors='replace')[:2000])
    try: validation = json.loads(checked.stdout.decode('utf-8-sig'))
    except (ValueError, UnicodeError): raise ExportUnavailable('Invalid ibcmd validation report') from None
    tables = validation.get('tables', [])
    if len(tables) != 1: raise ExportUnavailable('Missing scoped compiler coverage')
    coverage = tables[0].get('source_assets', {})
    if (coverage.get('status') != 'complete' or coverage.get('candidate_set_complete') is not True
            or not isinstance(coverage.get('expected'), int) or coverage.get('expected') != coverage.get('emitted')
            or any(coverage.get(key, 0) for key in ('opaque', 'missing', 'opaque_property_count'))):
        raise ExportUnavailable('Compiler reports incomplete selected source assets')
    for row in tables[0].get('metadata_root_inventory', {}).get('entries', []):
        if row.get('uuid') == oid and not row.get('emitted_path'):
            diagnostic = row.get('diagnostic') or {}
            raise ExportUnavailable('Compiler cannot render selected XML: '+diagnostic.get('code', 'unknown'))
    try:
        result = subprocess.run([str(executable), 'objects', 'export', '--rows-dir', str(source),
                                 '--target-dir', str(target), '--object', selected, '--platform', platform],
                                capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise ExportUnavailable('ibcmd selected-object export timed out') from None
    if result.returncode:
        message = (result.stderr or result.stdout).decode('utf-8', errors='replace')[:2000]
        raise ExportUnavailable('ibcmd selected-object export rejected: '+message)
    try: report = json.loads(result.stdout.decode('utf-8-sig'))
    except (ValueError, UnicodeError): raise ExportUnavailable('Invalid ibcmd object export report') from None
    objects = report.get('objects', [])
    if len(objects) != 1 or objects[0].get('object') != selected:
        raise ExportUnavailable('ibcmd did not export the selected object')
    files = {}; total = 0; found = False
    for name in objects[0].get('written', []):
        path = target/name
        if Path(name).is_absolute() or '..' in Path(name).parts or target.resolve() not in path.resolve().parents or path.is_symlink():
            raise ValueError('Unsafe compiler output path')
        if not path.is_file() or path.stat().st_size > s.MAX_BYTES:
            raise ExportUnavailable('Missing or oversized compiler file')
        raw = path.read_bytes(); total += len(raw)
        if total > s.MAX_STORAGE_BYTES: raise ValueError('Oversized selected export')
        files[name.replace('\\', '/')] = raw
        if path.suffix.lower() == '.xml':
            if b'<!DOCTYPE' in raw.upper(): raise ValueError('DOCTYPE is unsupported')
            node = E.fromstring(raw)
            if node.tag.endswith('}MetaDataObject') and any(child.get('uuid') == oid for child in node):
                try: files[name.replace('\\', '/')] = object_view_context.bind_children(raw, oid, context_plan['collections'], descriptions)
                except ValueError as error: raise ExportUnavailable(str(error)) from None
                found = True
    if not found: raise ExportUnavailable('Selected UUID missing from compiler XML')
    return files


def properties(raw):
    if raw is None: return {}
    if b'<!DOCTYPE' in raw.upper(): raise ValueError('DOCTYPE is unsupported')
    result = {}; seen = set()
    def visit(node, path):
        if path in seen: raise ValueError('Ambiguous XML child identity')
        seen.add(path)
        for key, value in sorted(node.attrib.items()): result[path+'/@'+key] = value
        if not len(node): result[path] = node.text or ''
        counts = {}
        for child in node:
            tag = child.tag.rsplit('}', 1)[-1]; counts[tag] = counts.get(tag, 0)+1
            identity = next((key+'='+child.get(key) for key in ('uuid', 'id', 'name') if child.get(key) is not None), str(counts[tag]))
            visit(child, path+'/'+tag+'['+identity+']')
    root = E.fromstring(raw); visit(root, root.tag.rsplit('}', 1)[-1])
    return result


def compare(request):
    executable = Path(request['executable']).resolve()
    if not executable.is_file(): raise ValueError('Missing ibcmd executable')
    oid = str(uuid.UUID(request['object_id']))
    if request.get('before') is None and request.get('after') is None:
        raise ValueError('At least one snapshot side is required')
    sides = {}
    with tempfile.TemporaryDirectory(prefix='crs-object-view-') as directory:
        for side in ('before', 'after'):
            if request.get(side) is None: sides[side] = {}; continue
            try:
                sides[side] = export(executable, request['platform'], request[side], oid, Path(directory)/side)
            except ExportUnavailable as error:
                return dict(status='unavailable', side=side, reason=str(error), representation='xml')
    files = []
    for name in sorted(set(sides['before']) | set(sides['after'])):
        before, after = sides['before'].get(name), sides['after'].get(name)
        if before == after: continue
        a, b = object_changes.value(before), object_changes.value(after)
        row = dict(path=name, before=a, after=b, action='create' if before is None else 'delete' if after is None else 'modify')
        if all(v['format'] == 'text' for v in (a, b) if v is not None):
            if sum(len(v) for v in (before, after) if v is not None) <= object_changes.MAX_DIFF_TEXT:
                row['diff'] = object_changes.text_diff(a['text'] if a else '', b['text'] if b else '', name)
            else: row['diff_omitted'] = 'text_size_limit'
        if name.lower().endswith('.xml'):
            left, right = properties(before), properties(after)
            row['properties'] = [dict(path=key, before=left.get(key), after=right.get(key))
                                 for key in sorted(set(left) | set(right)) if left.get(key) != right.get(key)]
        files.append(row)
    return dict(status='available', representation='xml', files=files)


if __name__ == '__main__':
    from serializer_cli import run
    def dispatch(request):
        if request.get('mode') != 'context': return compare(request)
        oid = str(uuid.UUID(request['object_id'])); raw = s.decode_storage(request['snapshot'])
        meta, _ = s.read_record(raw, 12); m = s.Parser(meta.decode('utf-8-sig')).documents()[0]
        data = external_data.extract(raw, oid)
        return object_view_context.plan(s.inflate(base64.b64decode(data['data'], validate=True)), oid,
                                        metadata_identifiers.class_labels()[s.val(m[2])], request['platform'])
    run(dispatch)
