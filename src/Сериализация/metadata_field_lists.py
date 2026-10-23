"""Complete metadata field lists with standard selectors or actual inline IDs."""
from xml.etree import ElementTree as E
import metadata_context
import metadata_common_xml
import native_metadata as s
import xml_namespaces
import object_xml_profiles as profiles

Q=metadata_common_xml.Q
XR='{'+xml_namespaces.READABLE+'}'


def add(index,name,path):
    if name in index or any(s.render(value)==s.render(path) for value in index.values()):raise ValueError('Duplicate metadata field identity')
    index[name]=path


def scalar_pattern(pattern,codes):
    return isinstance(pattern,list) and len(pattern)==2 and isinstance(pattern[1],list) and bool(pattern[1]) and s.val(pattern[1][0]) in codes


def xml_index(owner,kind,name,rule,indexed_only=False,standard_fields=None,scalar_types=None):
    prefix=profiles.xml_kind(kind)+'.'+name+'.';result={}
    props=owner.find(Q+'Properties')
    for field,spec in rule['standards'].items():
        if standard_fields is not None and field not in standard_fields:continue
        if 'length_property' in spec and props.findtext(Q+spec['length_property'])=='0':continue
        add(result,prefix+'StandardAttribute.'+field,[s.atom(spec['code'])])
    names=set();children=owner.find(Q+'ChildObjects')
    for node in ([] if children is None else children):
        if node.tag!=Q+'Attribute':continue
        field=node.findtext(Q+'Properties/'+Q+'Name') or ''
        if not field:raise ValueError('Invalid metadata field name')
        if field.casefold() in names:raise ValueError('Duplicate metadata field name')
        names.add(field.casefold())
        if indexed_only and node.findtext(Q+'Properties/'+Q+rule['index_property']) not in rule['indexed_values']:continue
        if scalar_types is not None:
            import type_description_xml
            try:pattern=type_description_xml.read_metadata(node.find(Q+'Properties/'+Q+'Type'))
            except ValueError:continue
            if not scalar_pattern(pattern,scalar_types):continue
        add(result,prefix+'Attribute.'+field,[s.atom(0),s.atom(metadata_context.guid(node.get('uuid')))])
    return result


def native_index(source,kind,name,rule,indexed_only=False,standard_fields=None,scalar_types=None):
    result={};prefix=profiles.xml_kind(kind)+'.'+name+'.'
    for field,spec in rule['standards'].items():
        if standard_fields is not None and field not in standard_fields:continue
        if 'length_path' in spec:
            length=source
            for slot in spec['length_path']:length=length[slot]
            if s.val(length)=='0':continue
        add(result,prefix+'StandardAttribute.'+field,[s.atom(spec['code'])])
    row=source
    for slot in rule['attributes_path']:row=row[slot]
    if len(row)<2 or s.val(row[1])!=str(len(row)-2):raise ValueError('Invalid native metadata field collection')
    for entry in row[2:]:
        if indexed_only:
            indexing=entry
            for slot in rule['indexing_path']:indexing=indexing[slot]
            if s.val(indexing) not in rule['indexed_native_values']:continue
        if scalar_types is not None:
            pattern=entry
            for slot in rule.get('attribute_type_path',[0,1,1,2]):pattern=pattern[slot]
            if not scalar_pattern(pattern,scalar_types):continue
        common=entry
        for slot in rule['attribute_common_path']:common=common[slot]
        add(result,prefix+'Attribute.'+s.val(common[2]),[s.atom(0),s.atom(metadata_context.guid(s.val(common[1][2])))])
    return result


def read(node,index,rule):
    if node is None:return None
    if node.attrib or (node.text or '').strip() or len(node)>1024:raise ValueError('Invalid metadata field list')
    result=[];seen=set()
    for item in node:
        value=item.text or ''
        if item.tag!=XR+'Field' or item.attrib or len(item) or value not in index or value in seen:raise ValueError('Missing, foreign or duplicate metadata field reference: '+value)
        seen.add(value);result.append([s.atom('#',True),s.atom(rule['type_id']),index[value]])
    return [s.atom(0),s.atom(len(result))]+result


def field_names(row,index,rule):
    if len(row)<2 or s.val(row[0])!='0' or s.val(row[1])!=str(len(row)-2):raise ValueError('Invalid native metadata field list')
    inverse={s.render(path):name for name,path in index.items()};seen=set();result=[]
    for item in row[2:]:
        if not isinstance(item,list) or len(item)!=3 or s.val(item[0])!='#' or s.val(item[1])!=rule['type_id']:raise ValueError('Unsupported native metadata field reference')
        value=inverse.get(s.render(item[2]))
        if value is None or value in seen:raise ValueError('Unknown or duplicate native metadata field')
        seen.add(value);result.append(value)
    return result


def export(node,row,index,rule):
    for value in field_names(row,index,rule):E.SubElement(node,XR+'Field').text=value
