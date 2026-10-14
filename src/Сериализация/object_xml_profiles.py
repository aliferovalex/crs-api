"""Registry of verified complete-object XML profiles and companion module files."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def profiles():
    return json.loads(Path(__file__).with_name('object_xml_profiles.json').read_text(encoding='utf-8-sig'))


def creation_types():
    return ('Constant',)+tuple(profiles())


def module_files(kind):
    return profiles().get(kind,{}).get('modules',{})
