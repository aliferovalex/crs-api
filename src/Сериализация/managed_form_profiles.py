"""Verified owner identities and native templates shared by form converters."""
import json
from functools import lru_cache
from pathlib import Path
import native_metadata as s

@lru_cache(maxsize=1)
def owner_profiles():
    return json.loads(Path(__file__).with_name('managed_form_owner_profiles_851.json').read_text(encoding='utf-8-sig'))


KINDS=tuple(owner_profiles())+('CommonForm',)


def form_kind(owner):return 'CommonForm' if owner=='CommonForm' else owner+'Form'


def owner_kind(form):
    for owner in KINDS:
        if form_kind(owner)==form:return owner
    raise ValueError('Unsupported managed form class: '+form)


def owner_common(owner,kind):
    if kind=='CommonForm':raise ValueError('Configuration has its own native property reader')
    node=owner
    try:
        for slot in owner_profiles()[kind]['owner_common_path']:node=node[slot]
    except (KeyError,IndexError,TypeError):raise ValueError('Unmapped or invalid native form owner: '+kind) from None
    return node


def layout(kind):
    names={'Catalog':'catalog','Document':'document','CommonForm':'common','DataProcessor':'dataprocessor','Report':'report'}
    if kind not in names:
        if kind not in owner_profiles():raise ValueError('Unsupported managed form kind')
        return owner_profiles()[kind]
    return json.loads(Path(__file__).with_name(names[kind]+'_form_layout_851.json').read_text(encoding='utf-8'))


def owner_name(owner,kind):
    if kind=='CommonForm':return ''
    return s.val(owner_common(owner,kind)[2])


def binding_owner(source,target,kind,*,allow_rename=False):
    """Use a compiled final owner for paths, retaining source identity/types.

    Batch builders pass this body after whole-object conversion. Snapshots and
    original versions always remain bound to the actual repository source.
    """
    if target is None or kind=='CommonForm':return source
    before=owner_common(source,kind);after=owner_common(target,kind)
    renamed=s.val(before[2])!=s.val(after[2])
    if s.val(before[1][2])!=s.val(after[1][2]) or renamed and not allow_rename:
        raise ValueError('Final form owner identity differs from source')
    import managed_form_xml
    old=managed_form_xml.object_paths(source,kind);new=managed_form_xml.object_paths(target,kind)
    expected=old.main_types
    if renamed:
        suffix='.'+s.val(before[2]);expected={}
        for key,value in old.main_types.items():
            if not key.endswith(suffix):raise ValueError('Unsupported final owner generated type name')
            expected[key[:-len(suffix)]+'.'+s.val(after[2])]=value
    if expected!=new.main_types:raise ValueError('Final form owner generated types differ from source')
    return target


def common(body,kind):
    node=body
    for slot in layout(kind).get('common_path',[1,1,1]):node=node[slot]
    return node


def replace_common(body,kind,value):
    path=layout(kind).get('common_path',[1,1,1]);node=body
    for slot in path[:-1]:node=node[slot]
    node[path[-1]]=value


def defaults(kind):
    if kind=='Document':return {'AutoTime':'CurrentOrLast','UsePostingMode':'Auto','RepostOnWrite':'true'}
    if kind=='Report':return {'ReportFormType':'Main','AutoShowState':'Auto','ReportResultViewMode':'Auto','ViewModeApplicationOnSetReportResult':'Auto'}
    return {}
