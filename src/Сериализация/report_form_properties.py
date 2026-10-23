"""Report-specific native properties; configuration URIs use the current context."""
import json
import uuid
from pathlib import Path
from functools import lru_cache
import native_metadata as s

Q='{http://v8.1c.ru/8.3/xcf/logform}'


@lru_cache(maxsize=1)
def profile():
    return json.loads(Path(__file__).with_name('report_form_properties_851.json').read_text(encoding='utf-8'))


def apply(form,root,owner_name,configuration_id=None):
    rule=profile();head=form[1];index=rule['counter'];count=int(s.val(head[index]));end=index+1+count*2
    if count<0 or end>len(head):raise ValueError('Invalid report property header')
    values={}
    for i in range(index+1,end,2):
        key=s.val(head[i])
        if key in values:raise ValueError('Duplicate report property')
        values[key]=head[i+1]
    if any(node.tag==Q+'Events' and len(node) for node in root.iter()):
        if configuration_id is None:raise ValueError('Report events require the Configuration UUID from current context')
        configuration_id=str(uuid.UUID(configuration_id))
        for key,text in rule['event_defaults'].items():values.setdefault(key,s.Parser(text).documents()[0])
        for key,number in rule['configuration_uris'].items():
            values[key]=[s.atom('S',True),s.atom('urn:form:md:'+str(number)+':'+configuration_id,True)]
        values[str(rule['owner_name_key'])]=[s.atom('S',True),s.atom(rule['owner_name_prefix']+owner_name,True)]
    for name,property_rule in rule['xml_properties'].items():
        if root.find(Q+name) is not None:values[str(property_rule['key'])]=s.Parser(property_rule['value']).documents()[0]
    entries=[]
    for key in sorted(values,key=int):entries.extend([s.atom(key),values[key]])
    head[index]=s.atom(len(values));head[index+1:end]=entries
