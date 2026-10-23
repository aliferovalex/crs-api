"""Registry of verified complete-object XML profiles and companion module files."""
import json
import copy
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def profiles():
    return json.loads(Path(__file__).with_name('object_xml_profiles.json').read_text(encoding='utf-8-sig'))


def creation_types():
    return tuple(profiles())


def change_types():
    return tuple(kind for kind, rule in profiles().items() if not rule.get('creation_only'))


def xml_kind(kind):
    """XML export names can differ from native repository class labels."""
    if kind in profiles():return profiles()[kind].get('xml_kind',kind)
    # Referenced classes do not need an active full-object converter.
    import metadata_structure
    try:return metadata_structure.profile(kind)['xml_name']
    except ValueError:return kind


def module_files(kind):
    return profiles().get(kind,{}).get('modules',{})


def content_files(kind):
    return profiles().get(kind,{}).get('files',{})


def generated_name(kind,category,name):
    rule=layout(kind) if kind in profiles() else {}
    return rule.get('generated_prefixes',{}).get(category,xml_kind(kind)+category)+'.'+name


def reference_type(kind):
    rule=layout(kind);category=rule.get('reference_category','Ref')
    if rule['generated_slots'] and category in rule.get('generated_categories',('Object','Ref','Selection','List','Manager')):
        return rule.get('reference_prefix',kind+'Ref'),category
    return None


def reference_types(kind):
    default=reference_type(kind);result={} if default is None else {default[0]:default[1]}
    rule=layout(kind)
    for category in rule.get('additional_reference_categories',[]):
        if category not in rule.get('generated_categories',('Object','Ref','Selection','List','Manager')):raise ValueError('Unknown reference category')
        result[generated_name(kind,category,'')[:-1]]=category
    return result


@lru_cache(maxsize=None)
def _layout(kind, platform_profile):
    value=json.loads(Path(__file__).with_name(kind.lower()+'_layout_851.json').read_text(encoding='utf-8'))
    value.update(value.pop('platform_overrides',{}).get(platform_profile,{}))
    import owned_form_properties,managed_form_profiles
    roles=owned_form_properties.profiles().get(kind,{}).get('properties',{})
    if roles:
        references=value.setdefault('reference_values',{})
        for name,path in roles.items():
            rule=dict(path=path,target=managed_form_profiles.form_kind(kind),owner_kind=kind)
            if name in references and references[name]!=rule:raise ValueError('Conflicting owner form reference profile: '+kind+'.'+name)
            references[name]=rule
    return value


def layout(kind, platform='8.5.1.1529'):
    """Full converters and opaque patches share the same native form-role map."""
    import platform_profiles
    return copy.deepcopy(_layout(kind,platform_profiles.profile(platform)))
