"""Read form owner identities and common native property paths."""
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


def owner_name(owner,kind):
    if kind=='CommonForm':return ''
    return s.val(owner_common(owner,kind)[2])
