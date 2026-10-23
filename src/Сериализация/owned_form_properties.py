"""Verified role references can be patched without rebuilding opaque owners."""
import metadata_context
import xml_namespaces
import json
from functools import lru_cache
from pathlib import Path
import native_metadata as s
import managed_form_profiles as owners
import metadata_targets

Q='{'+xml_namespaces.MD+'}'


@lru_cache(maxsize=1)
def profiles():
    return json.loads(Path(__file__).with_name('owned_form_properties_851.json').read_text(encoding='utf-8'))


def at(body,path):
    try:
        for slot in path:body=body[slot]
    except (IndexError,TypeError):raise ValueError('Unsupported native form role path') from None
    return body


def value(root,name,index,owner,kind):
    nodes=root[0].findall(Q+'Properties/'+Q+name)
    if len(nodes)>1:raise ValueError('Duplicate owner form property: '+name)
    if not nodes:return s.ZERO
    node=nodes[0]
    if node.attrib or len(node) or (node.text or '').strip()!=(node.text or ''):raise ValueError('Invalid owner form property: '+name)
    return index.owned_form(node.text,owner,kind) if node.text else s.ZERO


def patch(raw,kind,owner,before,after,source_targets,final_targets):
    profile=profiles().get(kind)
    if profile is None:return raw,{},{}
    def element(node):
        return node.tag,tuple(sorted(node.attrib.items())),node.text or '',tuple(element(child) for child in node)
    def signature(root,name):
        nodes=root[0].findall(Q+'Properties/'+Q+name)
        return tuple(element(node) for node in nodes)
    if all(signature(before,name)==signature(after,name) for name in profile['properties']):return raw,{},{}
    docs=s.Parser(raw.decode('utf-8-sig')).documents()
    if len(docs)!=1:raise ValueError('Unsupported form role body documents')
    body=docs[0]
    if len(body)!=profile['body_size'] or s.val(body[0])!=profile['body_version'] or s.val(body[1][0])!=profile['header_version']:
        raise ValueError('Unsupported native form role layout')
    common=owners.owner_common(body,kind)
    if s.val(common[1][2])!=owner:raise ValueError('Native form role owner identity differs')
    old_index=metadata_targets.index(source_targets);new_index=metadata_targets.index(final_targets)
    old={};new={};patches=[]
    for name,path in profile['properties'].items():
        node=at(body,path)
        if not isinstance(node,s.Atom) or node.quoted:raise ValueError('Unsupported native form role value')
        old[name]=value(before,name,old_index,owner,kind);new[name]=value(after,name,new_index,owner,kind)
        current=s.val(node)
        if (metadata_context.guid(current) if current!=s.ZERO else current)!=old[name]:raise ValueError('Source form role differs from snapshot: '+name)
        if old[name]!=new[name]:patches.append((node.start,node.end,new[name]))
    text=raw.decode('utf-8-sig')
    for start,end,replacement in sorted(patches,reverse=True):text=text[:start]+replacement+text[end:]
    prefix=b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    return prefix+text.encode('utf-8'),old,new
