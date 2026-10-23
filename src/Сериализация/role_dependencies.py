"""Reschedule retained whole role files when referenced metadata IDs disappear.

UUID changes can leave Rights.xml text unchanged because its references use
qualified names. Repository relation maps identify the affected source roles;
their complete target files are compiled against the final XML definitions.
"""
from pathlib import Path
import configuration_export
import metadata_context
import metadata_identifiers as ids
import native_metadata as s


def identities(inventory):
    return {metadata_context.guid(node.get('uuid'))
            for record in inventory.values() for node in record['node'].iter()
            if node.get('uuid')}


def expand(plan, target, objects, directory, baseline_directory):
    """Add dependent roles to the ordinary operation/snapshot preparation path."""
    roles = {oid: record for oid, record in target.items()
             if record['kind'] == 'Role' and oid in objects
             and s.val(objects[oid][0][2]) == ids.class_id('Role')}
    if not roles or not plan['operations']:
        return []
    # Pure companion changes cannot replace metadata identities.
    if not plan['removed_ids'] and not any(
            op.get('xml_path') in plan['xml_paths'] and target[op['object_id']]['path'] in op['changed_files']
            for op in plan['operations'] if op['operation'] != 'Удаление'):
        return []
    _, _, source, _ = configuration_export.inventory(baseline_directory)
    lost = identities(source) - identities(target)
    if not lost:
        return []
    selected = {op['object_id'] for op in plan['operations']}
    # xml_paths are absolute paths into the target export, including when only
    # another object's XML text changed. No synthetic edit is written to disk.
    directory = Path(directory).resolve()
    added = []
    for oid, record in sorted(roles.items()):
        if oid in selected or not (set(s.metadata_relations(objects[oid][0][14])) & lost):
            continue
        path = directory / record['path']
        companion = path.with_suffix('') / 'Ext/Rights.xml'
        if not companion.is_file():
            raise ValueError('Dependent role requires its complete target Rights.xml: ' + str(path))
        plan['operations'].append(dict(operation='Изменение', object_id=oid, kind='Role', xml_path=str(path),
                                       changed_files=[], reason='metadata_reference_changed'))
        plan['xml_paths'].append(str(path)); added.append(oid)
    plan['unchanged_count'] -= len(added)
    return added
