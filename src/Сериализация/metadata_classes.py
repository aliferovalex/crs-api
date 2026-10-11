"""Read-only class discovery from native Configuration collection maps.

The UUIDs are read from the snapshot, including empty collections. Labels are
optional hints from metadata_class_names.json, not a platform registry.
"""
import base64
import json
from pathlib import Path
import sys
import uuid
import comment_serializer as s

ROOT_CLASS = 'cf4abeab-37b2-11d4-940f-008048da11f9'
MAIN_GROUP = '9fcd25a0-4822-11d4-9414-008048da11f9'


def guid(node):
    value = s.val(node)
    result = str(uuid.UUID(value))
    if result != value.lower() or result == s.ZERO:
        raise ValueError('Invalid class/object UUID')
    return result


def count(node):
    value = s.val(node)
    if not value.isdecimal():
        raise ValueError('Invalid collection count')
    return int(value)


def discover(root, root_id, labels=None):
    """Parse the verified root format 2 and collection maps format 1.

    Unknown class UUIDs are retained; unknown structural formats are rejected.
    Feature/group UUIDs and instance UUIDs never become class entries.
    """
    labels = labels or {}
    if not isinstance(root, s.Group) or len(root) < 4 or s.val(root[0]) != '2':
        raise ValueError('Unsupported Configuration body')
    if not isinstance(root[1], s.Group) or len(root[1]) != 1 or guid(root[1][0]) != root_id:
        raise ValueError('Configuration UUID mismatch')
    features = count(root[2])
    if features != len(root) - 4:
        raise ValueError('Invalid feature count')
    classes = [dict(class_id=ROOT_CLASS, name='Configuration', object_count=1,
                    group_id=None, source='snapshot_metadata', name_source='repository_root')]
    groups, seen_classes, seen_groups, seen_objects = [], {ROOT_CLASS}, set(), {root_id}
    for feature in root[3:-1]:
        if not isinstance(feature, s.Group) or len(feature) != 2:
            raise ValueError('Invalid feature block')
        group_id = guid(feature[0])
        if group_id in seen_groups:
            raise ValueError('Duplicate feature group')
        seen_groups.add(group_id)
        data = feature[1]
        if group_id == MAIN_GROUP:
            if not isinstance(data, s.Group) or len(data) != 2 or s.val(data[0]) != '6':
                raise ValueError('Unsupported main group format')
            data = data[1]
        if not isinstance(data, s.Group) or len(data) < 3 or s.val(data[0]) != '1':
            raise ValueError('Unsupported collection map format')
        if not isinstance(data[1], s.Group) or count(data[2]) != len(data) - 3:
            raise ValueError('Invalid collection map count')
        groups.append(dict(group_id=group_id, class_count=len(data)-3))
        for row in data[3:]:
            if not isinstance(row, s.Group) or len(row) < 2:
                raise ValueError('Invalid collection row')
            class_id, objects = guid(row[0]), count(row[1])
            if objects != len(row) - 2:
                raise ValueError('Invalid collection object count')
            if class_id in seen_classes:
                raise ValueError('Duplicate class UUID')
            seen_classes.add(class_id)
            for node in row[2:]:
                object_id = guid(node)
                if object_id in seen_objects:
                    raise ValueError('Duplicate object UUID')
                seen_objects.add(object_id)
            name = labels.get(class_id)
            classes.append(dict(class_id=class_id, name=name, object_count=objects,
                                group_id=group_id, source='root_collection_map',
                                name_source='reference_lookup' if name else None))
    return dict(classes=classes, groups=groups, scope='configuration_top_level',
                complete_platform_registry=False)


def catalog(request):
    encoded = request['snapshot']
    if not isinstance(encoded, str) or len(encoded) > s.MAX_BYTES * 2:
        raise ValueError('Oversized or invalid snapshot')
    data = base64.b64decode(encoded, validate=True)
    s.validate_storage(data)
    raw_metadata, pos = s.read_record(data, 12)
    metadata = s.Parser(raw_metadata.decode('utf-8-sig')).documents()
    if len(metadata) != 3 or len(metadata[0]) != 17 or s.val(metadata[0][0]) != '5':
        raise ValueError('Unsupported snapshot metadata')
    root_id = guid(metadata[0][1])
    if root_id != request['object_id'] or guid(metadata[0][2]) != ROOT_CLASS:
        raise ValueError('A Configuration root snapshot is required')
    body, pos = s.read_record(data, pos)
    documents = s.Parser(s.inflate(body).decode('utf-8-sig')).documents()
    if len(documents) != 1:
        raise ValueError('Unsupported Configuration document count')
    labels = json.loads(Path(__file__).with_name('metadata_class_names.json').read_text(encoding='utf-8-sig'))
    result = discover(documents[0], root_id, labels['names'])
    result.update(ok=True, root_object_version=count(metadata[0][5]),
                  repository_version=request.get('repository_version'),
                  platform=request.get('platform'), label_reference=labels['source'])
    return result


def main():
    try:
        request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
        result = catalog(request)
    except Exception as error:
        result = dict(ok=False, error=str(error))
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
