"""Read profile-based inline collections and recursive identities."""
import xml_namespaces
import native_metadata as s

Q='{'+xml_namespaces.MD+'}'
XSD='http://www.w3.org/2001/XMLSchema'


def at(node,path):
    for slot in path:node=node[slot]
    return node


def entries(body,profile):
    row=at(body,profile.get('path',[profile.get('slot')]))
    if not isinstance(row,list) or len(row)<2 or s.val(row[0])!=profile['collection_id'] or s.val(row[1])!=str(len(row)-2):raise ValueError('Invalid inline child collection')
    return row[2:]


def identities(entry,profile,scope=None):
    oid=s.val(at(entry,profile['id_path']));scope=scope or profile.get('xml_name','Command');result=[(oid,scope)]
    for tag,rule in profile.get('children',{}).items():
        for child in entries(entry,rule):result.extend(identities(child,rule,scope+'.'+oid+'.'+tag))
    if len({key for key,_ in result})!=len(result):raise ValueError('Duplicate inline UUID')
    return result
