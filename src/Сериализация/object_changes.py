"""Lossless native snapshot comparison; unknown streams remain opaque."""
import base64
import difflib
import hashlib
import uuid
import external_data
import native_metadata as s
import serialization_context

MAX_DIFF_TEXT = 512 * 1024


def stream_manifest(request):
    oid = str(uuid.UUID(request['object_id']))
    raw = s.decode_storage(request['snapshot'])
    row = external_data.extract_many(raw, {oid}, partial_externals=not request.get('complete', False))[oid]
    metadata, _ = s.read_record(raw, 12)
    m = s.Parser(metadata.decode('utf-8-sig')).documents()[0]
    if s.val(m[1]) != oid:
        raise ValueError('Unexpected first snapshot object')
    refs = serialization_context.external_versions(m[11])
    return dict(streams=[dict(name=name, version=uuid.UUID(version).bytes_le.hex()+'00000000')
                         for name, version in sorted(refs.items())],
                original=row['original'], local=row['local'])


def text_diff(before, after, name):
    lines = difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                 fromfile='before/'+name, tofile='after/'+name)
    # difflib leaves unterminated source lines unterminated too. Preserve that
    # fact explicitly, otherwise the removed/added lines run into one another.
    return ''.join(line if line.endswith('\n') else line+'\n\\ No newline at end of file\n'
                   for line in lines)


def snapshot(encoded, oid):
    row = external_data.extract(s.decode_storage(encoded), oid)
    streams = {'$body': s.inflate(base64.b64decode(row['data'], validate=True))}
    for stream in row['externals']:
        streams[stream['name']] = s.inflate(base64.b64decode(stream['data'], validate=True))
    return row, streams


def value(raw):
    if raw is None:
        return None
    result = dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                  data=base64.b64encode(raw).decode('ascii'))
    try:
        text = raw.decode('utf-8-sig')
        if any(ord(c) < 32 and c not in '\r\n\t' for c in text):
            raise ValueError('Binary control characters')
        result.update(format='text', text=text)
    except (UnicodeDecodeError, ValueError):
        result['format'] = 'binary'
    return result


def compare(request):
    oid = str(uuid.UUID(request['object_id']))
    before, after = request.get('before'), request.get('after')
    if before is None and after is None:
        raise ValueError('At least one complete snapshot is required')
    old_meta, old = snapshot(before, oid) if before is not None else (None, {})
    new_meta, new = snapshot(after, oid) if after is not None else (None, {})
    if old_meta and new_meta and old_meta['class_id'] != new_meta['class_id']:
        raise ValueError('Object class changed for the same UUID')
    changes = []
    for name in sorted(set(old) | set(new)):
        left, right = old.get(name), new.get(name)
        if left == right:
            continue
        row = dict(name=name, action='create' if left is None else 'delete' if right is None else 'modify',
                   before=value(left), after=value(right))
        sides = [side for side in (row['before'], row['after']) if side is not None]
        if all(side['format'] == 'text' for side in sides):
            if sum(side['size'] for side in sides) <= MAX_DIFF_TEXT:
                a = row['before']['text'] if left is not None else ''
                b = row['after']['text'] if right is not None else ''
                row['diff'] = text_diff(a, b, name)
            else:
                row['diff_omitted'] = 'text_size_limit'
        changes.append(row)
    return dict(object_id=oid, action='create' if before is None else 'delete' if after is None else 'modify',
                before=old_meta, after=new_meta, streams=changes,
                content_changed=bool(changes), representation='native')


if __name__ == '__main__':
    from serializer_cli import run
    run(lambda request: stream_manifest(request) if request.get('mode') == 'streams' else compare(request))
