"""Verified inline children reuse common properties and scalar Type conversion."""
import copy
from xml.etree import ElementTree as E
import inline_attribute_xml as x
import native_metadata as s
import type_description_xml as types
import metadata_common_xml


def read(node,profile,*,type_references=None):
    if set(node.attrib)!={'uuid'} or len(node)!=1 or node[0].tag!=x.Q+'Properties' or node[0].attrib:raise ValueError('Unsupported inline object structure')
    props=node[0];fields={n.tag.removeprefix(x.Q):n for n in props}
    if len(fields)!=len(props) or any(n.tag!=x.Q+k for k,n in fields.items()):raise ValueError('Duplicate or foreign inline property')
    pattern=types.read_metadata(fields.get('Type'),type_references)
    if profile.get('allowed_type_codes') and any(s.val(arm[0]) not in profile['allowed_type_codes'] for arm in pattern[1:]):raise ValueError('Unsupported inline scalar type for this collection')
    if profile.get('properties') is not None and set(fields)-set(profile['properties']):raise ValueError('Inline property is outside its owner profile')
    defaults=x.attribute_defaults(pattern,filling=profile.get('filling',True));defaults.update(profile['defaults'])
    for key,n in fields.items():
        if key in x.scalar_properties():continue
        if key not in ('Name','Synonym','Comment','Type') and (key not in defaults or metadata_common_xml.canonical(n)!=defaults[key]):raise ValueError('Unsupported inline property: '+key)
    xml_name=profile.get('xml_name','Attribute');top=E.Element(x.Q+xml_name,uuid=node.get('uuid'));p=E.SubElement(top,x.Q+'Properties')
    for key in ('Name','Synonym','Comment','Type')+tuple(x.scalar_properties()):
        if key in fields:p.append(copy.deepcopy(fields[key]))
    return x.attribute_xml(top,profile['template'],type_references=type_references,filling=profile.get('filling',True),property_names=profile.get('properties'),xml_name=xml_name)


def features(body,layout):
    result=[s.val(entry[0][1][1][1][1][2]) for profile in layout.get('inline_collections',{}).values() for entry in body[profile['slot']][2:]]
    if 'values_slot' in layout:
        result.extend(s.val(entry[0][1][1][2]) for entry in body[layout['values_slot']][2:])
    import tabular_section_xml as tabular
    for profile in layout.get('tabular_collections',{}).values():
        for entry in body[profile['slot']][2:]:result.extend(tabular.feature_ids(entry))
    import inline_command_xml as commands
    result.extend(commands.features(body,layout))
    import inline_metadata_xml
    for rule in layout.get('structured_collections',{}).values():
        for entry in inline_metadata_xml.entries(body,rule):result.extend(oid for oid,_ in inline_metadata_xml.identities(entry,rule))
    if len(set(result))!=len(result):raise ValueError('Duplicate inline feature UUID')
    return result


def scopes(body,layout):
    result={s.val(entry[0][1][1][1][1][2]):name for name,profile in layout.get('inline_collections',{}).items() for entry in body[profile['slot']][2:]}
    if 'values_slot' in layout:
        result.update((s.val(entry[0][1][1][2]),'EnumValue') for entry in body[layout['values_slot']][2:])
    import tabular_section_xml as tabular
    for name,profile in layout.get('tabular_collections',{}).items():
        for entry in body[profile['slot']][2:]:
            oid=s.val(tabular.common(entry)[1][2]);result[oid]=name
            for attr in tabular.attributes(entry):result[s.val(attr[0][1][1][1][1][2])]=name+'.'+oid
    import inline_command_xml as commands
    for name,profile in layout.get('command_collections',{}).items():
        for entry in body[profile['slot']][2:]:result[s.val(commands.at(entry,profile['id_path']))]=name
    import inline_metadata_xml
    for rule in layout.get('structured_collections',{}).values():
        for entry in inline_metadata_xml.entries(body,rule):result.update(inline_metadata_xml.identities(entry,rule))
    return result
