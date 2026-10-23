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
import preparation_plan as preparation
import object_xml_profiles as profiles

Q=preparation.Q
D='{http://v8.1c.ru/8.3/xcf/dumpinfo}'


def folder(tag):
    return {'BusinessProcess':'BusinessProcesses','FilterCriterion':'FilterCriteria','ChartOfAccounts':'ChartsOfAccounts','ChartOfCharacteristicTypes':'ChartsOfCharacteristicTypes','ChartOfCalculationTypes':'ChartsOfCalculationTypes'}.get(tag,tag if tag.endswith('s') else tag+'s')


def inventory(directory):
    base=Path(directory).resolve()
    if not base.is_dir():raise ValueError('Missing export directory')
    files={};objects={};by_path={};total=0
    for path in sorted(base.rglob('*')):
        if path.is_symlink() or base not in path.resolve().parents:raise ValueError('Export path escapes its directory')
        if not path.is_file():continue
        name=path.relative_to(base).as_posix();raw=path.read_bytes();total+=len(raw)
        if len(raw)>s.MAX_BYTES or total>s.MAX_BYTES*8 or len(files)>=65536:raise ValueError('Oversized configuration export')
        files[name]=raw
        if path.suffix.lower()!='.xml' or name=='ConfigDumpInfo.xml':continue
        if b'<!DOCTYPE' in raw.upper():raise ValueError('Export DOCTYPE is unsupported')
        node=E.fromstring(raw)
        if node.tag!=Q+'MetaDataObject':continue
        kind,oid,label=preparation.metadata(raw.decode('utf-8-sig'));structure.profile(kind)
        if oid in objects:raise ValueError('Duplicate export object UUID')
        record=dict(id=oid,kind=kind,name=label,path=name,node=node[0],files=[name],parent_id=None)
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


def module_companions(record,objects):
    """Map complete-export module paths to their declared stream owners."""
    prefix=str(Path(record['path']).with_suffix('')).replace('\\','/')+'/'
    kind=runtime_kind(record,objects)
    if kind=='CommonModule':return {prefix+'Ext/Module.bsl':('module_text','Module')}
    if record['kind'] in ('Form','CommonForm'):return {prefix+'Ext/Form/Module.bsl':('module_text','Module')}
    result={prefix+'Ext/'+module+'.bsl':('modules',module) for module in profiles.module_files(kind)}
    if kind in profiles.profiles() and profiles.layout(kind).get('command_collections'):
        children=record['node'].find(Q+'ChildObjects')
        for node in ([] if children is None else children):
            if node.tag!=Q+'Command':continue
            name=node.findtext(Q+'Properties/'+Q+'Name') or ''
            if not name or Path(name).name!=name or '/' in name or '\\' in name or name in ('.','..'):raise ValueError('Invalid command module path')
            result[prefix+'Commands/'+name+'/Ext/CommandModule.bsl']=('inline_modules',metadata_context.guid(node.get('uuid')))
    return result


def supported_companion(record,name,objects):
    prefix=str(Path(record['path']).with_suffix('')).replace('\\','/')+'/'
    local=name[len(prefix):] if name.startswith(prefix) else name
    kind=runtime_kind(record,objects)
    if record['kind'] in ('Form','CommonForm'):return local in ('Ext/Form.xml','Ext/Form/Module.bsl')
    if record['kind'] in ('Template','CommonTemplate'):return local in ('Ext/Template.xml','Ext/Template.txt','Ext/Template.bin')
    if kind=='CommonModule':return local=='Ext/Module.bsl'
    if local in {'Ext/'+rule['file'] for rule in profiles.content_files(kind).values()}:return True
    return prefix+local in module_companions(record,objects)


def fingerprint(files):
    rows=[(name,hashlib.sha256(raw).hexdigest()) for name,raw in sorted(files.items())]
    return hashlib.sha256(json.dumps(rows,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()


def relocated_files(prior,record):
    """Match a definition and its companions across owner/name path changes."""
    if prior is None:return {}
    old_prefix=prior['path'][:-4]+'/'
    new_prefix=record['path'][:-4]+'/'
    return {record['path'] if name==prior['path'] else new_prefix+name[len(old_prefix):]:name for name in prior['files']}


def plan(request):
    base,old_files,old,old_root=inventory(request['baseline_directory'])
    target,new_files,new,new_root=inventory(request['directory'])
    objects=metadata_context.context_objects(request['context'])
    baseline_versions(old_files.get('ConfigDumpInfo.xml'),objects)
    if set(old)!=set(objects):raise ValueError('Source export must contain every stored repository object')
    for oid,record in old.items():
        m=objects[oid][0];kind=runtime_kind(record,old)
        profile=structure.profile(record['kind'])
        cls=(next(r['item_class_id'] for r in structure.profile(old[record['parent_id']]['kind'])['collections'] if r['xml_name']=='Form') if record['kind']=='Form' else profile['class_id'])
        if cls!=s.val(m[2]) or record['parent_id']!=s.val(m[3]) or record['name']!=s.val(m[9]):raise ValueError('Source export identity differs from repository')
        prefix=str(Path(record['path']).with_suffix('')).replace('\\','/')+'/'
        companions={name[len(prefix):] if name.startswith(prefix) else name for name in record['files'] if name!=record['path']}
        if record['kind'] in ('Form','CommonForm') and 'Ext/Form.xml' not in companions:raise ValueError('Source export is missing Form.xml')
        if kind=='CommonModule' and s.val(m[11][0])!='0' and 'Ext/Module.bsl' not in companions:raise ValueError('Source export is missing Module.bsl')
        if {'Ext/'+rule['file'] for rule in profiles.content_files(kind).values() if rule.get('required')}-companions:raise ValueError('Source export is missing required companion files')
        if record['kind'] in ('Template','CommonTemplate') and s.val(m[11][0])!='0' and not companions.intersection(('Ext/Template.xml','Ext/Template.bin','Ext/Template.txt')):
            raise ValueError('Source export is missing template contents')
    if old_root['id']!=new_root['id']:raise ValueError('Target export belongs to another configuration')
    operations=[]
    for oid,record in new.items():
        prior=old.get(oid);changed=[]
        if prior and (prior['kind']!=record['kind'] or prior['parent_id']!=record['parent_id']):raise ValueError('Export class or owner cannot change for an existing UUID')
        previous=relocated_files(prior,record)
        names=set(record['files'])|set(previous)
        for name in sorted(names):
            if old_files.get(previous.get(name,name))!=new_files.get(name):changed.append(name)
        if prior and not changed:continue
        source_modules=module_companions(prior,old) if prior else {}
        old_modules={name:source_modules[source] for name,source in previous.items() if source in source_modules};new_modules=module_companions(record,new)
        supplied={value for name,value in new_modules.items() if name in new_files};declared=set(new_modules.values());module_removals={}
        for name in changed:
            if name not in new_files and name in old_modules:
                category,module=old_modules[name]
                # The same command module can move when its command is renamed.
                # A command removed from XML drops its stream in the owner converter.
                if (category,module) in declared and (category,module) not in supplied:
                    if category=='module_text':module_removals['clear_module_text']=True
                    else:module_removals.setdefault('removed_'+category,[]).append(module)
                continue
            if name!=record['path'] and name not in new_modules and not supported_companion(record,name,new):raise ValueError('Unsupported changed export companion: '+name)
            if name not in new_files:raise ValueError('Removed companion needs an explicit final content: '+name)
        operations.append(dict(operation='Изменение' if prior else 'Создание',object_id=oid,kind=runtime_kind(record,new),
                               xml_path=str(target/record['path']),changed_files=changed,**module_removals))
    removed=[oid for oid in old if oid not in new]
    for oid in removed:
        record=old[oid]
        operations.append(dict(operation='Удаление',object_id=oid,kind=runtime_kind(record,old),parent_id=record['parent_id']))
    return dict(operations=operations,removed_ids=removed,new_ids=[oid for oid in new if oid not in old],
                xml_paths=[op['xml_path'] for op in operations if op['operation']=='Изменение'],target_fingerprint=fingerprint(new_files),
                baseline_fingerprint=fingerprint(old_files),object_count=len(new),unchanged_count=sum(oid in old and oid not in {op['object_id'] for op in operations} for oid in new))


if __name__=='__main__':
    from serializer_cli import run
    run(plan)
