"""Verified standard Picture XML references shared by form adapters."""
import copy,json
from pathlib import Path
import native_metadata as s

XR='{http://v8.1c.ru/8.3/xcf/readable}'


def profile():
    return json.loads(Path(__file__).with_name('standard_picture_layout_851.json').read_text(encoding='utf-8'))


def read(node):
    data=profile();result=s.Parser(data['empty_template']).documents()[0]
    if node is None:return result
    if node.attrib or (node.text or '').strip() or any((n.tail or '').strip() for n in node):raise ValueError('Unsupported Picture XML')
    if not len(node):return result
    fields={n.tag:n for n in node}
    if len(fields)!=len(node) or set(fields)!={XR+'Ref',XR+'LoadTransparent'}:raise ValueError('Picture requires Ref and LoadTransparent')
    if any(n.attrib or len(n) for n in fields.values()):raise ValueError('Unsupported nested Picture property')
    reference=fields[XR+'Ref'].text or '';prefix='StdPicture.'
    if not reference.startswith(prefix) or reference[len(prefix):] not in data['references']:raise ValueError('Unsupported or unverified picture reference: '+reference)
    transparent=fields[XR+'LoadTransparent'].text
    if transparent not in ('true','false'):raise ValueError('Invalid picture LoadTransparent')
    result[1]=s.atom(1);result[2]=s.Parser(data['references'][reference[len(prefix):]]).documents()[0]
    result[data['transparent_slot']]=s.atom(1 if transparent=='true' else 0)
    return result


def put(entry,path,value):
    target=entry
    for slot in path[:-1]:target=target[slot]
    target[path[-1]]=copy.deepcopy(value)
