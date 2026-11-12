"""Plan complete hierarchical export changes against a version-bound baseline.

ConfigDumpInfo binds the source export to repository objects and streams. File
contents, not its potentially stale target versions, determine the change set.
"""
import metadata_context
import hashlib,json,re,uuid
from pathlib import Path
from xml.etree import ElementTree as E
import native_metadata as s
import metadata_structure as structure
import export_xml as preparation
import native_object_profiles as profiles
import xml_compare
import resource_limits as limits

Q=preparation.Q
D='{http://v8.1c.ru/8.3/xcf/dumpinfo}'


def folder(tag):
    return {'BusinessProcess':'BusinessProcesses','FilterCriterion':'FilterCriteria','ChartOfAccounts':'ChartsOfAccounts','ChartOfCharacteristicTypes':'ChartsOfCharacteristicTypes','ChartOfCalculationTypes':'ChartsOfCalculationTypes'}.get(tag,tag if tag.endswith('s') else tag+'s')


def export_paths(base):
    """Git worktrees and the local CRS cache are not configuration files."""
    def walk(directory):
        for path in sorted(directory.iterdir()):
            if directory==base and path.name in ('.git','.gitignore','.crs-cache'):continue
            if path.is_symlink() or base not in path.resolve().parents:raise ValueError('Export path escapes its directory')
            if path.is_dir():yield from walk(path)
            elif path.is_file():yield path
    return walk(base)


def require_complete_directory(directory):
    base=Path(directory).resolve()
    if (base/'.crs-partial.json').exists():
        raise ValueError('Partial XML workspace cannot use complete-configuration preparation; use its coverage map and addressed module preparation')


def inventory(directory):
    base=Path(directory).resolve()
    if not base.is_dir():raise ValueError('Missing export directory')
    require_complete_directory(base)
    files={};objects={};by_path={};total=0
    for path in export_paths(base):
        if len(files)>=limits.get('export_files',65536):raise ValueError('Configuration export exceeds export_files')
        if path.stat().st_size>limits.get('export_file_bytes',s.MAX_BYTES) or total+path.stat().st_size>limits.get('export_total_bytes',s.MAX_BYTES*8):raise ValueError('Oversized configuration export')
        name=path.relative_to(base).as_posix();raw=path.read_bytes();total+=len(raw)
        if len(raw)>limits.get('export_file_bytes',s.MAX_BYTES) or total>limits.get('export_total_bytes',s.MAX_BYTES*8):raise ValueError('Oversized configuration export')
        files[name]=raw
        if path.suffix.lower()!='.xml' or name=='ConfigDumpInfo.xml':continue
        if b'<!DOCTYPE' in raw.upper():raise ValueError('Export DOCTYPE is unsupported')
        node=E.fromstring(raw)
        if node.tag!=Q+'MetaDataObject':continue
        kind,oid,label=preparation.metadata(raw.decode('utf-8-sig'));structure.profile(kind)
        if oid in objects:raise ValueError('Duplicate export object UUID')
        record=dict(id=oid,kind=kind,name=label,path=name,node=node[0],xml=raw.decode('utf-8-sig'),files=[name],parent_id=None)
        objects[oid]=record;by_path[name]=record
    if 'Configuration.xml' not in by_path or by_path['Configuration.xml']['kind']!='Configuration':raise ValueError('Complete export requires Configuration.xml')
    root=by_path['Configuration.xml'];root['parent_id']=s.ZERO;visiting=set();visited=set()
    def walk(owner):
        if owner['id'] in visiting:raise ValueError('Cyclic export object tree')
        if owner['id'] in visited:raise ValueError('Export object has multiple owners')
        visiting.add(owner['id']);visited.add(owner['id'])
        children=owner['node'].find(Q+'ChildObjects');rules={r['xml_name']:r for r in structure.profile(owner['kind'])['collections']}
        seen=set()
        for node in ([] if children is None else children):
            tag=node.tag.removeprefix(Q);rule=rules.get(tag)
            if node.tag!=Q+tag or rule is None:raise ValueError('Unknown export child collection')
            if rule['storage']!='stored_name':continue
            name=node.text or ''
            if node.attrib or len(node) or not name or '/' in name or '\\' in name or name in ('.','..') or (tag,name) in seen:raise ValueError('Invalid or duplicate stored export child')
            seen.add((tag,name))
            prefix='' if owner is root else str(Path(owner['path']).with_suffix('')).replace('\\','/')+'/'
            path=prefix+folder(tag)+'/'+name+'.xml';child=by_path.get(path)
            if child is None or child['kind']!=rule['item_type'] or child['name']!=name:raise ValueError('Missing or inconsistent stored export child: '+path)
            child['parent_id']=owner['id'];walk(child)
        visiting.remove(owner['id'])
    walk(root)
    if visited!=set(objects):raise ValueError('Orphan metadata file outside the exported child tree')
    # The closest metadata definition owns each companion directory. Root streams
    # are exported under Ext/, rather than under a Configuration/ directory.
    owners=sorted(objects.values(),key=lambda r:len(r['path']),reverse=True)
    for name in files:
        if name in by_path or name=='ConfigDumpInfo.xml':continue
        candidates=[r for r in owners if name.startswith(str(Path(r['path']).with_suffix('')).replace('\\','/')+'/')]
        if not candidates and name.startswith('Ext/'):candidates=[root]
        if not candidates:raise ValueError('Unowned export file: '+name)
        candidates[0]['files'].append(name)
    return base,files,objects,root


def baseline_versions(raw,objects):
    if raw is None or b'<!DOCTYPE' in raw.upper():raise ValueError('Source export needs ConfigDumpInfo.xml')
    top=E.fromstring(raw)
    if top.tag!=D+'ConfigDumpInfo' or top.get('format')!='Hierarchical':raise ValueError('Only hierarchical source exports are supported')
    found={};expected={}
    for oid,docs in objects.items():
        m=docs[0];expected[oid]=uuid.UUID(s.val(m[8])).bytes_le.hex()+'00000000'
        row=m[11]
        if len(row)!=1+2*int(s.val(row[0])):raise ValueError('Invalid repository external map')
        for i in range(1,len(row),2):expected[s.val(row[i])]=uuid.UUID(s.val(row[i+1])).bytes_le.hex()+'00000000'
    for node in top.iter(D+'Metadata'):
        value=node.get('configVersion')
        if value is None:continue # Inline fields do not have separate repository bodies.
        oid=node.get('id')
        if oid in found or not re.fullmatch('[0-9a-fA-F]{40}',value):raise ValueError('Invalid source export version map')
        found[oid]=value.lower()
    if found!=expected:raise ValueError('Source export object/stream versions differ from the current repository')


def runtime_kind(record,objects):
    if record['kind']=='Form':return structure.profile(objects[record['parent_id']]['kind'])['runtime_name']+'Form'
    return structure.profile(record['kind'])['runtime_name']


def class_id(record,objects,source_hint=None):
    if record['parent_id']==s.ZERO:return structure.profile(record['kind'])['class_id']
    parent=objects[record['parent_id']]
    rules=[row for row in structure.profile(parent['kind'])['collections'] if row['storage']=='stored_name' and row['item_type']==record['kind']]
    values={row['item_class_id'] for row in rules if row.get('item_class_id')}
    if len(values)>1:raise ValueError('Ambiguous stored metadata class: '+record['kind'])
    bindings={value for value in (next(iter(values),None),record.get('_class_id'),objects.get(record.get('id'),{}).get('_class_id'),source_hint) if value}
    if len(bindings)>1:raise ValueError('Bound metadata class differs from schema/source: '+record['kind'])
    if bindings:return next(iter(bindings))
    raise ValueError('Missing stored metadata class: '+record['kind'])


def fingerprint(files):
    rows=[(name,hashlib.sha256(raw).hexdigest()) for name,raw in sorted(files.items())]
    return hashlib.sha256(json.dumps(rows,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()


def relocated_files(prior,record):
    """Match a definition and its companions across owner/name path changes."""
    if prior is None:return {}
    old_prefix=prior['path'][:-4]+'/'
    new_prefix=record['path'][:-4]+'/'
    return {record['path'] if name==prior['path'] else new_prefix+name[len(old_prefix):]:name for name in prior['files']}


def positions(objects):
    """Positions are per class within the owner's declared child collection."""
    lookup={(row['parent_id'],row['kind'],row['name']):oid for oid,row in objects.items()}
    result={}
    for parent,row in objects.items():
        children=row['node'].find(Q+'ChildObjects');counts={}
        for child in ([] if children is None else children):
            kind=child.tag.removeprefix(Q);oid=lookup.get((parent,kind,child.text))
            if oid is None:continue
            result[oid]=counts.get(kind,0);counts[kind]=result[oid]+1
    return result


def plan(request):
    base,old_files,old,old_root=inventory(request['baseline_directory'])
    target,new_files,new,new_root=inventory(request['directory'])
    objects=metadata_context.context_objects(request['context'])
    baseline_versions(old_files.get('ConfigDumpInfo.xml'),objects)
    if set(old)!=set(objects):raise ValueError('Source export must contain every stored repository object')
    for oid,record in old.items():
        m=objects[oid][0];kind=runtime_kind(record,old)
        cls=class_id(record,old,s.val(m[2]))
        if cls!=s.val(m[2]) or record['parent_id']!=s.val(m[3]) or record['name']!=s.val(m[9]):raise ValueError('Source export identity differs from repository')
        prefix=str(Path(record['path']).with_suffix('')).replace('\\','/')+'/'
        companions={name[len(prefix):] if name.startswith(prefix) else name for name in record['files'] if name!=record['path']}
        if record['kind'] in ('Form','CommonForm') and 'Ext/Form.xml' not in companions:raise ValueError('Source export is missing Form.xml')
        if kind=='CommonModule' and s.val(m[11][0])!='0' and 'Ext/Module.bsl' not in companions:raise ValueError('Source export is missing Module.bsl')
        if {'Ext/'+rule['file'] for rule in profiles.content_files(kind).values() if rule.get('required')}-companions:raise ValueError('Source export is missing required companion files')
        if record['kind'] in ('Template','CommonTemplate') and s.val(m[11][0])!='0' and not companions.intersection(('Ext/Template.xml','Ext/Template.bin','Ext/Template.txt')):
            raise ValueError('Source export is missing template contents')
    if old_root['id']!=new_root['id']:raise ValueError('Target export belongs to another configuration')
    operations=[];ordinals=positions(new)
    for oid,record in new.items():
        prior=old.get(oid);changed=[]
        if prior and (prior['kind']!=record['kind'] or prior['parent_id']!=record['parent_id']):raise ValueError('Export class or owner cannot change for an existing UUID')
        previous=relocated_files(prior,record)
        names=set(record['files'])|set(previous)
        for name in sorted(names):
            if not xml_compare.file_equal(name,old_files.get(previous.get(name,name)),new_files.get(name)):changed.append(name)
        position_changed=prior is not None and oid in ordinals and int(s.val(objects[oid][0][10]))!=ordinals[oid]
        if prior and not changed and not position_changed:continue
        operations.append(dict(operation='Изменение' if prior else 'Создание',object_id=oid,kind=runtime_kind(record,new),
                               xml_path=str(target/record['path']),changed_files=changed,position=ordinals.get(oid),position_changed=position_changed))
    removed=[oid for oid in old if oid not in new]
    for oid in removed:
        record=old[oid]
        operations.append(dict(operation='Удаление',object_id=oid,kind=runtime_kind(record,old),parent_id=record['parent_id']))
    return dict(operations=operations,removed_ids=removed,new_ids=[oid for oid in new if oid not in old],
                capture_ids=sorted(op['object_id'] for op in operations if op['operation']!='Создание'),
                xml_paths=[op['xml_path'] for op in operations if op['operation']=='Изменение'],target_fingerprint=fingerprint(new_files),
                baseline_fingerprint=fingerprint(old_files),object_count=len(new),unchanged_count=sum(oid in old and oid not in {op['object_id'] for op in operations} for oid in new))


if __name__=='__main__':
    from serializer_cli import run
    run(plan)
