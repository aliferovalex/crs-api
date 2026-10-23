"""Verified QName types shared by metadata operations and parameters."""
import json,re
from pathlib import Path
from functools import lru_cache
import native_metadata as s
import typed_value_xml
import xml_namespaces


@lru_cache(maxsize=1)
def types():
    return json.loads(Path(__file__).with_name('xdto_types_851.json').read_text(encoding='utf-8'))['types']


def freeze(available=None):
    return tuple(sorted((uri,tuple(sorted(names))) for uri,names in (types() if available is None else available).items()))


def bindings(available=None):
    result={'xs':typed_value_xml.XSD}
    for index,uri in enumerate(sorted(set(types() if available is None else available)-{typed_value_xml.XSD})):result['xdto'+str(index)]=uri
    return result


def name(node,namespaces):
    text=(node.text or '').strip()
    if node.attrib or len(node) or not re.fullmatch(r'(?:[^\W\d][\w.-]*:)?[^\W\d][\w.-]*',text):raise ValueError('Invalid XDTO type QName')
    return typed_value_xml.qname(text,xml_namespaces.context(namespaces,node))


def read(node,namespaces,available=None):
    uri,local=name(node,namespaces)
    if local not in (types() if available is None else available).get(uri,[]):raise ValueError('Unsupported or unbound XDTO type QName')
    return [s.atom(0),s.atom(uri,True),s.atom(local,True)]


def write(node,value,available=None):
    if not isinstance(value,list) or len(value)!=3 or s.val(value[0])!='0':raise ValueError('Unsupported native XDTO QName')
    uri,name=s.val(value[1]),s.val(value[2])
    if name not in (types() if available is None else available).get(uri,[]):raise ValueError('Unsupported native XDTO QName')
    prefix=next(key for key,namespace in bindings(available).items() if namespace==uri);node.text=prefix+':'+name
