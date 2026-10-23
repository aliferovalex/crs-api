"""Shared scalar attribute XML and verified inline body templates."""
import copy,json
from pathlib import Path
from xml.etree import ElementTree as E
import native_metadata as s
import metadata_context
import metadata_common_xml as common
from functools import lru_cache
import type_description_xml as types
from metadata_common_xml import Q


@lru_cache(maxsize=1)
def scalar_properties():
    return json.loads(Path(__file__).with_name('catalog_attribute_layout_851.json').read_text(encoding='utf-8')).get('scalar_properties',{})


def at(node,path):
    for slot in path:node=node[slot]
    return node


def canonical_filling(entry,*,filling=True):
    """A non-string field's unused empty-string default exports as XML nil."""
    pattern=entry[0][1][1][2]
    if filling and not any(s.val(arm[0])=='S' for arm in pattern[1:]) and s.render(entry[0][1][19])=='{"S",""}':
        result=copy.deepcopy(entry);result[0][1][19]=[s.atom('U',True)];return result
    return entry


def attribute_export(entry,template=None,*,type_references=None,filling=True,property_names=None,xml_name='Attribute'):
    properties=entry[0][1][1][1];pattern=entry[0][1][1][2]
    node=E.Element(Q+xml_name,uuid=s.val(properties[1][2]));props=E.SubElement(node,Q+'Properties');common.write(props,properties)
    props.append(types.export_metadata(pattern,Q+'Type',type_references))
    defaults=attribute_defaults(pattern,filling=filling)
    if property_names is not None:defaults={key:value for key,value in defaults.items() if key in property_names}
    def restore(value):
        tag,attrs,text,children=value;n=E.Element(tag,attrs);n.text=text
        for child in children:n.append(restore(child))
        return n
    for value in defaults.values():props.append(restore(value))
    for key,rule in scalar_properties().items():
        property_node=props.find(Q+key)
        if property_node is not None:property_node.text=common.scalar_text(at(entry,rule['path']),rule)
    _,_,rebuilt=attribute_xml(node,template,type_references=type_references,filling=filling,property_names=property_names,xml_name=xml_name)
    if s.render(rebuilt)!=s.render(canonical_filling(entry,filling=filling)):raise ValueError('Source Attribute properties are outside the verified XML profile')
    return node


def attribute_defaults(pattern,*,filling=True):
    defaults=json.loads(Path(__file__).with_name('catalog_attribute_xml_defaults.json').read_text(encoding='utf-8'))
    if not any(s.val(arm[0])=='S' for arm in pattern[1:]):
        defaults['FillValue']=[Q+'FillValue',{'{http://www.w3.org/2001/XMLSchema-instance}nil':'true'},'',[]]
    if not filling:
        for name in ('FillValue','FillFromFillingValue'):defaults.pop(name,None)
    return defaults


def attribute_xml(node,template=None,*,type_references=None,filling=True,property_names=None,xml_name='Attribute'):
    if node.tag!=Q+xml_name or set(node.attrib)!={'uuid'} or len(node)!=1 or node[0].tag!=Q+'Properties' or node[0].attrib:
        raise ValueError('Expected inline '+xml_name+'/Properties')
    aid=metadata_context.guid(node.get('uuid'));props=node[0]
    fields={v.tag.removeprefix(Q):v for v in props}
    if len(fields)!=len(props) or any(v.tag!=Q+k for k,v in fields.items()):raise ValueError('Duplicate or unexpected Attribute property')
    if property_names is not None and set(fields)-set(property_names):raise ValueError('Attribute property is outside its owner profile')
    defaults=attribute_defaults(types.read_metadata(fields.get('Type'),type_references),filling=filling)
    for name,value in fields.items():
        if name in scalar_properties():
            if value.attrib or len(value):raise ValueError('Invalid Attribute scalar property: '+name)
            common.scalar_value(value.text or '',scalar_properties()[name]);continue
        if name not in ('Name','Synonym','Comment','Type') and (name not in defaults or common.canonical(value)!=defaults[name]):
            raise ValueError('Unsupported Attribute property: '+name)
    name,properties=common.read(props,aid)
    pattern=types.read_metadata(fields.get('Type'),type_references)
    if template is None:template=json.loads(Path(__file__).with_name('catalog_attribute_layout_851.json').read_text(encoding='utf-8'))['template']
    entry=s.Parser(template).documents()[0]
    entry[0][1][1][1]=copy.deepcopy(properties);entry[0][1][1][2]=copy.deepcopy(pattern)
    for key,rule in scalar_properties().items():
        if key in fields:at(entry,rule['path'][:-1])[rule['path'][-1]]=s.atom(common.scalar_value(fields[key].text or '',rule))
    # A template can originate from either a string field or a typed flag.
    # Full XML defaults determine the value independently of that template.
    if filling:entry[0][1][19]=([s.atom('S',True),s.atom('',True)] if any(s.val(arm[0])=='S' for arm in pattern[1:]) else [s.atom('U',True)])
    return aid,name,entry
