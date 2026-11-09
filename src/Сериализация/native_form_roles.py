"""Read native owner form-role profiles."""
import xml_namespaces
import json
from functools import lru_cache
from pathlib import Path

Q='{'+xml_namespaces.MD+'}'


@lru_cache(maxsize=1)
def profiles():
    return json.loads(Path(__file__).with_name('owned_form_properties_851.json').read_text(encoding='utf-8'))
