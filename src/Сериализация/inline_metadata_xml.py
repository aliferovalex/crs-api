"""Profile-driven inline metadata properties and recursive child collections."""
import metadata_common_xml
import metadata_context
import xml_namespaces
import copy
from xml.etree import ElementTree as E
import native_metadata as s
import metadata_localized_xml as localized
import type_description_xml as types
import xdto_type_xml

Q='{'+xml_namespaces.MD+'}'
XSD='http://www.w3.org/2001/XMLSchema'


def at(node,path):
    for slot in path:node=node[slot]
    return node


def read(node,profile,*,type_references=None,bindings=None,xdto_types=None):
    tag=profile.get('xml_name','Command')
    if (node.tag!=Q+tag or set(node.attrib)!={'uuid'} or len(node) not in (1,2) or node[0].tag!=Q+'Properties' or node[0].attrib
            or len(node)==2 and (not profile.get('children') or node[1].tag!=Q+'ChildObjects' or node[1].attrib)):raise ValueError('Expected inline '+tag+'/Properties')
    oid=metadata_context.guid(node.get('uuid'));fields={n.tag.removeprefix(Q):n for n in node[0]}
    if len(fields)!=len(node[0]) or any(n.tag!=Q+k for k,n in fields.items()):raise ValueError('Duplicate or foreign '+tag.lower()+' property')
    if set(profile.get('required_properties',[]))-set(fields):raise ValueError('Missing required inline properties')
    for key,n in fields.items():
        if key in ('Name','Synonym','Comment'):continue
        if key in profile.get('scalar_properties',{}):
            if n.attrib or len(n) or (n.text or '') not in profile['scalar_properties'][key]['values']:raise ValueError('Unsupported '+tag.lower()+' property value: '+key)
            continue
        if key in profile.get('localized_properties',{}):continue
        if key in profile.get('string_properties',{}):
            if n.attrib or len(n) or '\0' in (n.text or ''):raise ValueError('Invalid inline string property: '+key)
            continue
        if key in profile.get('qname_properties',{}):continue
        if key=='CommandParameterType' and profile.get('type_path'):continue
        if key not in profile['defaults'] or n.attrib or len(n) or (n.text or '')!=profile['defaults'][key]:raise ValueError('Unsupported '+tag.lower()+' property: '+key)
    name,common=metadata_common_xml.read(node[0],oid)
    entry=s.Parser(profile['template']).documents()[0];at(entry,profile['common_path'][:-1])[profile['common_path'][-1]]=copy.deepcopy(common);at(entry,profile['id_path'][:-1])[profile['id_path'][-1]]=s.atom(oid)
    def assign(path,value):at(entry,path[:-1])[path[-1]]=value
    for key,rule in profile.get('scalar_properties',{}).items():
        if key in fields:assign(rule['path'],s.atom(rule['values'][fields[key].text or '']))
    for key,path in profile.get('localized_properties',{}).items():assign(path,localized.read(fields.get(key),key))
    for key,path in profile.get('string_properties',{}).items():
        if key in fields:assign(path,s.atom(fields[key].text or '',True))
    for key,rule in profile.get('qname_properties',{}).items():
        if key in fields:
            assign(rule['path'],xdto_type_xml.read(fields[key],bindings,xdto_types))
    if profile.get('type_path'):
        parameter=fields.get('CommandParameterType')
        if parameter is not None and (parameter.attrib or (parameter.text or '').strip()):raise ValueError('Unsupported CommandParameterType structure')
        pattern=[s.atom('Pattern',True)] if parameter is None or not len(parameter) else types.read_metadata(parameter,type_references)
        assign(profile['type_path'],pattern)
    identities_seen={oid};names={key:set() for key in profile.get('children',{})};children=node.find(Q+'ChildObjects')
    if children is not None and ((children.text or '').strip() or len(children)>1024):raise ValueError('Invalid inline children')
    for child in ([] if children is None else children):
        key=child.tag.removeprefix(Q);rule=profile.get('children',{}).get(key)
        if child.tag!=Q+key or rule is None or (child.tail or '').strip():raise ValueError('Unsupported inline child')
        cid,cname,value=read(child,rule,type_references=type_references,bindings=bindings,xdto_types=xdto_types);ids={key for key,_ in identities(value,rule)}
        if identities_seen&ids or cname.casefold() in names[key]:raise ValueError('Duplicate inline UUID or name')
        identities_seen.update(ids);names[key].add(cname.casefold());row=at(entry,rule['path']);entries(entry,rule);row.append(value);row[1]=s.atom(len(row)-2)
    return oid,name,entry


def export(entry,profile,*,type_references=None,xdto_types=None):
    """Restore a complete inline object, checking every native field."""
    tag=profile.get('xml_name','Command');oid=s.val(at(entry,profile['id_path']));node=E.Element(Q+tag,uuid=oid)
    props=E.SubElement(node,Q+'Properties');metadata_common_xml.write(props,at(entry,profile['common_path']))
    for key,value in profile['defaults'].items():E.SubElement(props,Q+key).text=value
    def field(key):
        node=props.find(Q+key)
        return E.SubElement(props,Q+key) if node is None else node
    for key,rule in profile.get('scalar_properties',{}).items():
        values=[label for label,value in rule['values'].items() if str(value)==s.val(at(entry,rule['path']))]
        if len(values)!=1:raise ValueError('Unsupported native '+tag.lower()+' property: '+key)
        field(key).text=values[0]
    for key,path in profile.get('localized_properties',{}).items():localized.write(field(key),at(entry,path),key)
    for key,path in profile.get('string_properties',{}).items():field(key).text=s.val(at(entry,path))
    for key,rule in profile.get('qname_properties',{}).items():
        xdto_type_xml.write(field(key),at(entry,rule['path']),xdto_types)
    if profile.get('type_path'):
        pattern=at(entry,profile['type_path']);parameter=field('CommandParameterType')
        if s.render(pattern)!='{"Pattern"}':
            converted=types.export_metadata(pattern,Q+'CommandParameterType',type_references);parameter.extend(converted)
    if profile.get('children'):
        children=E.SubElement(node,Q+'ChildObjects')
        for rule in profile['children'].values():
            for child in entries(entry,rule):children.append(export(child,rule,type_references=type_references,xdto_types=xdto_types))
    _,_,rebuilt=read(node,profile,type_references=type_references,bindings=xdto_type_xml.bindings(xdto_types),xdto_types=xdto_types)
    if s.render(rebuilt)!=s.render(entry):raise ValueError('Source '+tag+' is outside the verified XML profile')
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
