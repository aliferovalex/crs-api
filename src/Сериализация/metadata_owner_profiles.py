"""Verified common layouts of existing owners, including non-form containers."""
import json
from functools import lru_cache
from pathlib import Path
import managed_form_profiles
import native_collection_editor as collections


@lru_cache(maxsize=1)
def owner_profiles():
    forms=managed_form_profiles.owner_profiles()
    extra=json.loads(Path(__file__).with_name('opaque_owner_profiles_851.json').read_text(encoding='utf-8'))
    if forms.keys() & extra.keys():raise ValueError('Duplicate native owner profile')
    return dict(forms,**extra)


def owner_common(body,kind):
    if kind not in owner_profiles():raise ValueError('Unsupported native metadata owner')
    return collections.at(body,owner_profiles()[kind]['owner_common_path'])
