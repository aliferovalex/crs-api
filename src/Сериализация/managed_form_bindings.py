"""Context-derived main types and verified register field paths."""
import copy,json,re,uuid
from functools import lru_cache
from pathlib import Path
import native_metadata as s
import managed_form_profiles as profiles


@lru_cache(maxsize=1)
def owners():
    return json.loads(Path(__file__).with_name('managed_form_bindings_851.json').read_text(encoding='utf-8'))['owners']


def at(node,path):
    try:
        for slot in path:node=node[slot]
    except (IndexError,TypeError):raise ValueError('Unsupported native main binding layout') from None
    return node


def attach_types(paths,owner,kind):
    profile=owners().get(kind)
    if profile is None or owner is None:return paths
    if 'body_size' in profile and (len(owner)!=profile['body_size'] or s.val(owner[0])!=profile['body_version'] or s.val(owner[1][0])!=profile['header_version']):raise ValueError('Unsupported register main binding layout')
    name=profiles.owner_name(owner,kind);seen=set();oid=s.val(profiles.owner_common(owner,kind)[1][2])
    for category,path in profile['types'].items():
        value=str(uuid.UUID(s.val(at(owner,path))))
        if value in seen or value in (s.ZERO,oid):raise ValueError('Invalid main attribute generated type UUID')
        import object_xml_profiles
        seen.add(value);key='cfg:'+object_xml_profiles.generated_name(kind,category,name);paths.main_types[key]=value
        if category=='RecordSet':paths.main_collections.add(key)
    return paths


def register_fields(paths,owner,kind):
    """Read inline fields from known groups; do not reinterpret stored children."""
    profile=owners()[kind];seen=set();names=set()
    for check in profile.get('mode_checks',[]):
        if not matches(owner,[check]):raise ValueError('Unsupported register binding mode')
    from managed_form_xml import scalar_type
    for group in profile['inline_groups']:
        row=at(owner,[group['slot']])
        if not isinstance(row,list) or len(row)<2 or s.val(row[0])!=group['class_id'] or int(s.val(row[1]))!=len(row)-2:raise ValueError('Invalid register field collection')
        for entry in row[2:]:
            common=at(entry,[0,1,1,1]);pattern=at(entry,[0,1,1,2])
            if (not isinstance(common,list) or len(common)!=9 or s.val(common[0])!='3'
                    or not isinstance(pattern,list) or not pattern or s.val(pattern[0])!='Pattern'):raise ValueError('Unsupported register inline field')
            name=s.val(common[2]);oid=str(uuid.UUID(s.val(common[1][2])))
            if not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE) or name.casefold() in names or oid==s.ZERO or oid in seen:raise ValueError('Duplicate or invalid register field identity')
            names.add(name.casefold());seen.add(oid);key='Object.'+name
            paths[key]=[s.atom(2),[s.atom(1)],[s.atom(0),s.atom(oid)]];paths.types[key]=scalar_type(pattern)
    standards=dict(profile['standard_fields'])
    for rule in profile.get('standard_field_rules',[]):
        if matches(owner,rule['when']):standards.update(rule['fields'])
    for name,(code,type_code) in standards.items():
        if name.casefold() in names:raise ValueError('Register field shadows a standard field')
        key='Object.'+name;paths[key]=[s.atom(2),[s.atom(1)],[s.atom(code)]];paths.types[key]=type_code
    return paths


def matches(owner,conditions):
    return all(('values' not in condition or s.val(at(owner,condition['path'])) in condition['values'])
               and ('not_values' not in condition or s.val(at(owner,condition['path'])) not in condition['not_values']) for condition in conditions)


def main_type(paths,form,key,kind,owner_name):
    available=getattr(paths,'main_types',{})
    if key in available:return available[key]
    if available or kind not in ('Catalog','Document','DataProcessor','Report') or key!='cfg:'+kind+'Object.'+owner_name:
        raise ValueError('Main attribute binding type does not match its owner or mapped profile: '+key)
    # Direct interface conversion may only have the original native form context.
    entries=[e for e in form[3][2:2+int(s.val(form[3][1]))] if s.val(e[10])=='1']
    if len(entries)!=1:raise ValueError('Main attribute requires its owner type context')
    pattern=entries[0][5]
    if len(pattern)!=2 or len(pattern[1])!=2 or s.val(pattern[1][0])!='#':raise ValueError('Unsupported native main attribute type')
    value=str(uuid.UUID(s.val(pattern[1][1])))
    if value==s.ZERO:raise ValueError('Empty main attribute type')
    return value


def retarget(paths,name,number,collection):
    from managed_form_xml import ObjectPaths
    result=ObjectPaths();result.references.update(getattr(paths,'references',{}));result.main_types.update(getattr(paths,'main_types',{}));result.main_collections.update(getattr(paths,'main_collections',set()))
    def rename(key):return name+key[len('Object'):] if key=='Object' or key.startswith('Object.') else key
    for key,value in (paths or {}).items():
        new_key=rename(key);value=copy.deepcopy(value)
        if key=='Object' or key.startswith('Object.'):
            if not isinstance(value,list) or len(value)<2 or s.render(value[1])!='{1}':raise ValueError('Unsupported main attribute path root')
            value[1]=[s.atom(number)]
        if new_key in result:raise ValueError('Ambiguous main attribute path')
        result[new_key]=value
    result.types.update({rename(k):v for k,v in getattr(paths,'types',{}).items()})
    result.tables.update(rename(k) for k in getattr(paths,'tables',set()))
    if collection:result[name]=[s.atom(1),[s.atom(number)]];result.tables.add(name)
    return result
