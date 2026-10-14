"""Inline command definitions use common properties and owned module streams."""
import copy
from xml.etree import ElementTree as E
import metadata_serializer as s
import constant_serializer as c

Q='{'+c.MD+'}'


def at(node,path):
    for slot in path:node=node[slot]
    return node


def read(node,profile):
    if node.tag!=Q+'Command' or set(node.attrib)!={'uuid'} or len(node)!=1 or node[0].tag!=Q+'Properties' or node[0].attrib:raise ValueError('Expected inline Command/Properties')
    oid=c.guid(node.get('uuid'));fields={n.tag.removeprefix(Q):n for n in node[0]}
    if len(fields)!=len(node[0]) or any(n.tag!=Q+k for k,n in fields.items()):raise ValueError('Duplicate or foreign command property')
    for key,n in fields.items():
        if key in ('Name','Synonym','Comment'):continue
        if key not in profile['defaults'] or n.attrib or len(n) or (n.text or '')!=profile['defaults'][key]:raise ValueError('Unsupported command property: '+key)
    top=E.Element(Q+'MetaDataObject',version='2.21');obj=E.SubElement(top,Q+'Constant',uuid=oid);props=E.SubElement(obj,Q+'Properties')
    for key in ('Name','Synonym','Comment'):
        if key in fields:props.append(copy.deepcopy(fields[key]))
    E.SubElement(E.SubElement(props,Q+'Type'),'{'+c.CORE+'}Type').text='xs:boolean'
    _,name,raw,_=c.constant_xml(E.tostring(top,encoding='unicode'),'8.5.1.1529');common=s.Parser(raw.decode('utf-8-sig')).documents()[0][1][1][1][1]
    entry=s.Parser(profile['template']).documents()[0];at(entry,profile['common_path'][:-1])[profile['common_path'][-1]]=copy.deepcopy(common);at(entry,profile['id_path'][:-1])[profile['id_path'][-1]]=s.atom(oid)
    return oid,name,entry


def features(body,layout):
    return [s.val(at(entry,profile['id_path'])) for profile in layout.get('command_collections',{}).values() for entry in body[profile['slot']][2:]]


def streams(body,layout):
    return {s.val(at(entry,profile['id_path'])):s.val(at(entry,profile['id_path']))+profile['module_suffix'] for profile in layout.get('command_collections',{}).values() for entry in body[profile['slot']][2:]}


def module_inputs(values,owners):
    if isinstance(values,list):
        if len(values)>1024 or any(not isinstance(entry,dict) or set(entry)!={'object_id','source_text'} for entry in values):raise ValueError('Invalid inline command module array')
        modules={entry['object_id']:entry['source_text'] for entry in values}
        if len(modules)!=len(values):raise ValueError('Duplicate inline command module owner')
    elif isinstance(values,dict):modules=values
    else:raise ValueError('Invalid inline command module input')
    if len(modules)>1024 or set(modules)-set(owners) or any(not isinstance(text,str) for text in modules.values()):raise ValueError('Invalid inline command module owners or texts')
    if sum(len(text.encode('utf-8')) for text in modules.values())>s.MAX_BYTES:raise ValueError('Oversized inline command modules')
    return modules
