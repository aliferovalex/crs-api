"""Whole metadata ValueLists partitioned into object references and strings."""
from xml.etree import ElementTree as E
import native_metadata as s
import metadata_identifiers as ids
import metadata_targets
import typed_value_xml as values
import xml_namespaces

XR='{'+xml_namespaces.READABLE+'}'


def read(node,rule,objects,scopes):
    references=[];strings=[]
    if node is None:return references,strings
    if node.attrib or (node.text or '').strip() or len(node)>1024:raise ValueError('Invalid metadata ValueList')
    index=metadata_targets.index(objects)
    for item in node:
        if (item.tag!=XR+'Item' or item.attrib or (item.text or '').strip() or (item.tail or '').strip()
                or [child.tag for child in item]!=[XR+'Presentation',XR+'CheckState',XR+'Value']):raise ValueError('Unsupported metadata ValueList Item')
        presentation,check,value=item
        if presentation.attrib or len(presentation) or (presentation.text or '') or check.attrib or len(check) or check.text!='0':raise ValueError('Unsupported metadata ValueList presentation or check state')
        if set(value.attrib)!={values.XSI+'type'} or len(value) or any((child.tail or '').strip() for child in item):raise ValueError('Invalid metadata ValueList value')
        uri,kind=values.qname(value.get(values.XSI+'type'),xml_namespaces.context(scopes,value));text=value.text or ''
        if (uri,kind)==(xml_namespaces.READABLE,'MDObjectRef'):
            prefix=rule['target']+'.'
            if not text.startswith(prefix):raise ValueError('Unexpected metadata ValueList reference class')
            matches=[row for row in index.find({ids.class_id(rule['target'])},text[len(prefix):]) if row.owner_id==s.ZERO]
            if len(matches)!=1 or matches[0].object_id in references:raise ValueError('Missing, ambiguous or duplicate metadata ValueList reference')
            references.append(matches[0].object_id)
        elif (uri,kind)==(values.XSD,'string'):
            if not text or '\0' in text or text in strings:raise ValueError('Empty or duplicate metadata ValueList namespace')
            strings.append(text)
        else:raise ValueError('Unsupported metadata ValueList value type')
    return references,strings


def string_row(strings):return [s.atom(len(strings))]+[s.atom(value,True) for value in strings]


def export(node,reference_row,strings,rule,index):
    if not isinstance(strings,list) or not strings or s.val(strings[0])!=str(len(strings)-1):raise ValueError('Invalid native ValueList namespace count')
    def item(kind,text):
        entry=E.SubElement(node,XR+'Item');E.SubElement(entry,XR+'Presentation');E.SubElement(entry,XR+'CheckState').text='0';value=E.SubElement(entry,XR+'Value',{values.XSI+'type':kind});value.text=text
    node.set('xmlns:mdref',xml_namespaces.READABLE)
    for entry in reference_row[2:]:
        value=entry
        for slot in rule['id_path']:value=value[slot]
        item('mdref:MDObjectRef',index.qualified(s.val(value)))
    for value in strings[1:]:
        if isinstance(value,list) or not value.quoted:raise ValueError('Invalid native ValueList namespace')
        item('xs:string',s.val(value))
