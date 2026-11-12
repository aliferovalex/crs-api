"""Context-derived main types and verified register field paths."""
import json, re, uuid
from functools import lru_cache
from pathlib import Path
import native_metadata as s
import native_form_profiles as profiles


@lru_cache(maxsize=1)
def profile():
    return json.loads(Path(__file__).with_name('managed_form_bindings_851.json').read_text(encoding='utf-8'))


def owners():
    return profile()['owners']


def at(node,path):
    try:
        for slot in path:node=node[slot]
    except (IndexError,TypeError):raise ValueError('Unsupported native main binding layout') from None
    return node


def validate_owner_properties(node,owner,kind):
    """Check measured native modes even when the compiler's own export agrees."""
    checks=owners().get(kind,{}).get('native_property_checks',{})
    if not checks:return
    properties=node.find('{http://v8.1c.ru/8.3/MDClasses}Properties')
    if properties is None:return
    for name,rule in checks.items():
        expected=properties.findtext('{http://v8.1c.ru/8.3/MDClasses}'+name)
        if expected is None:continue
        actual=s.val(at(owner,rule['path']))
        if rule.get('integer'):
            actual=str(int(actual));expected=str(int(expected))
        else:
            if actual not in rule['values']:raise ValueError('Unsupported native owner property mode: '+kind+'.'+name)
            actual=rule['values'][actual]
        if actual!=expected:raise ValueError('Native owner property differs from XML: '+kind+'.'+name)


def attach_types(paths,owner,kind):
    profile=owners().get(kind)
    if profile is None or owner is None:return paths
    if 'body_size' in profile and (len(owner)!=profile['body_size'] or s.val(owner[0])!=profile['body_version'] or s.val(owner[1][0])!=profile['header_version']):raise ValueError('Unsupported register main binding layout')
    name=profiles.owner_name(owner,kind);seen=set();oid=s.val(profiles.owner_common(owner,kind)[1][2])
    for category,path in profile['types'].items():
        value=str(uuid.UUID(s.val(at(owner,path))))
        if value in seen or value in (s.ZERO,oid):raise ValueError('Invalid main attribute generated type UUID')
        import native_object_profiles
        seen.add(value);key='cfg:'+native_object_profiles.generated_name(kind,category,name);paths.main_types[key]=value
        if category=='RecordSet':paths.main_collections.add(key)
    return paths


def inline_fields(owner,groups,seen):
    """Read measured inline groups within one field namespace."""
    names=set()
    for group in groups:
        row=at(owner,[group['slot']])
        if not isinstance(row,list) or len(row)<2 or s.val(row[0])!=group['class_id'] or int(s.val(row[1]))!=len(row)-2:raise ValueError('Invalid register field collection')
        for entry in row[2:]:
            common=at(entry,[0,1,1,1]);pattern=at(entry,[0,1,1,2])
            if (not isinstance(common,list) or len(common)!=9 or s.val(common[0])!='3'
                    or not isinstance(pattern,list) or not pattern or s.val(pattern[0])!='Pattern'):raise ValueError('Unsupported register inline field')
            name=s.val(common[2]);oid=str(uuid.UUID(s.val(common[1][2])))
            if not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE) or name.casefold() in names or oid==s.ZERO or oid in seen:raise ValueError('Duplicate or invalid register field identity')
            names.add(name.casefold());seen.add(oid)
            yield name,oid,pattern


def register_fields(paths,owner,kind):
    """Read inline fields from known groups; do not reinterpret stored children."""
    profile=owners()[kind];seen=set();names=set()
    for check in profile.get('mode_checks',[]):
        if not matches(owner,[check]):raise ValueError('Unsupported register binding mode')
    from native_form_reader import scalar_type
    for name,oid,pattern in inline_fields(owner,profile['inline_groups'],seen):
        names.add(name.casefold());key='Object.'+name
        paths[key]=[s.atom(2),[s.atom(1)],[s.atom(0),s.atom(oid)]];paths.types[key]=scalar_type(pattern)
    standards=dict(profile['standard_fields'])
    for rule in profile.get('standard_field_rules',[]):
        if matches(owner,rule['when']):standards.update(rule['fields'])
    for name,(code,type_code) in standards.items():
        if name.casefold() in names:raise ValueError('Register field shadows a standard field')
        key='Object.'+name;paths[key]=[s.atom(2),[s.atom(1)],[s.atom(code)]];paths.types[key]=type_code
    for name,rule in profile.get('standard_collections',{}).items():
        fields=list(inline_fields(owner,rule.get('inline_groups',[]),seen))
        if not matches(owner,rule.get('when',[])):continue
        key='Object.'+name
        if name.casefold() in names or key in paths:raise ValueError('Field shadows a standard collection')
        marker=s.atom(rule['marker'])
        paths[key]=[s.atom(2),[s.atom(1)],[marker]];paths.tables.add(key)
        for column,(code,type_code) in rule['columns'].items():
            field=key+'.'+column
            paths[field]=[s.atom(3),[s.atom(1)],[marker],[s.atom(code)]];paths.types[field]=type_code
        reserved={column.casefold() for column in rule['columns']}
        for column,oid,pattern in fields:
            if column.casefold() in reserved:raise ValueError('Inline field shadows a standard column')
            field=key+'.'+column
            paths[field]=[s.atom(3),[s.atom(1)],[marker],[s.atom(0),s.atom(oid)]];paths.types[field]=scalar_type(pattern)
    return paths


def matches(owner,conditions):
    return all(('values' not in condition or s.val(at(owner,condition['path'])) in condition['values'])
               and ('not_values' not in condition or s.val(at(owner,condition['path'])) not in condition['not_values']) for condition in conditions)
