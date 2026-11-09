"""Shared complete-export versions and safe snapshot file writing."""
from pathlib import Path
import re,uuid
from xml.etree import ElementTree as E
import configuration_export as export


def version_map(files):
    raw=files.get('ConfigDumpInfo.xml')
    if raw is None or b'<!DOCTYPE' in raw.upper():raise ValueError('XML baseline needs ConfigDumpInfo.xml')
    root=E.fromstring(raw)
    if root.tag!=export.D+'ConfigDumpInfo' or root.get('format')!='Hierarchical':raise ValueError('Only hierarchical XML is supported')
    result={}
    for row in root.iter(export.D+'Metadata'):
        value=row.get('configVersion')
        if value is None:continue
        oid=row.get('id')
        if oid in result or not re.fullmatch('[0-9a-fA-F]{40}',value):raise ValueError('Invalid XML versions')
        result[oid]=value.lower()
    return result


def expected_versions(state):
    result={oid:row['local'] for oid,row in state['objects'].items()}
    for row in state['objects'].values():result.update(row['externals'])
    return {key:uuid.UUID(value).bytes_le.hex()+'00000000' for key,value in result.items()}


def write_files(directory,files,*,exclusive=False):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    for name,raw in files.items():
        path=directory/name
        if Path(name).is_absolute() or '..' in Path(name).parts or directory.resolve() not in path.resolve().parents:raise ValueError('Invalid XML output path')
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb' if exclusive else 'wb') as output:output.write(raw)
