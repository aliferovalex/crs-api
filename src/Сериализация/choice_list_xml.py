"""Complete design-time ChoiceList shared by input fields and radio buttons."""
import json
from functools import lru_cache
from pathlib import Path
import metadata_serializer as s
import typed_value_xml as values
import picture_xml

Q='{http://v8.1c.ru/8.3/xcf/logform}'
XR='{http://v8.1c.ru/8.3/xcf/readable}'


@lru_cache(maxsize=1)
def profile():
    return json.loads(Path(__file__).with_name('choice_list_layout_851.json').read_text(encoding='utf-8'))


def fields(node,allowed,attributes=None):
    if set(node.attrib)!=(attributes or set()) or (node.text or '').strip():raise ValueError('Unsupported ChoiceList structure')
    result={}
    for child in node:
        if child.tag not in allowed or child.tag in result or (child.tail or '').strip():raise ValueError('Unsupported or duplicate ChoiceList property')
        result[child.tag]=child
    return result


def read(node,namespaces,references=None):
    from managed_form_elements import scalar,title
    a=s.atom;data=profile();result=[a(data['version']),a(0)]
    if node is None:return result
    if node.attrib or (node.text or '').strip() or len(node)>1024:raise ValueError('Invalid ChoiceList')
    tails=[]
    for item in node:
        if item.tag!=XR+'Item' or (item.tail or '').strip():raise ValueError('Expected readable ChoiceList Item')
        parts=fields(item,{XR+'Presentation',XR+'CheckState',XR+'Value'})
        if set(parts)!={XR+'Presentation',XR+'CheckState',XR+'Value'}:raise ValueError('Incomplete ChoiceList Item')
        design=parts[XR+'Value']
        if set(design.attrib)!={values.XSI+'type'} or values.qname(design.get(values.XSI+'type'),namespaces)!=(Q[1:-1],'FormChoiceListDesTimeValue'):raise ValueError('Expected FormChoiceListDesTimeValue')
        inner=fields(design,{Q+'Presentation',Q+'Value'},{values.XSI+'type'})
        if set(inner)!={Q+'Presentation',Q+'Value'}:raise ValueError('Incomplete design-time choice value')
        caption=title(inner[Q+'Presentation'])
        for row in caption[2:]:row[1]=a(values.native_text(s.val(row[1])),True)
        value_node=inner[Q+'Value'];reference=values.qname(value_node.get(values.XSI+'type',''),namespaces)==(XR[1:-1],'DesignTimeRef')
        if reference:
            if value_node.attrib!={values.XSI+'type':value_node.get(values.XSI+'type')} or len(value_node):raise ValueError('Invalid enum choice reference')
            ref=value_node.text or ''
            if ref not in (references or {}):raise ValueError('Unresolved design-time reference: '+ref)
            type_id,value_id=references[ref];payload=[a(1),a(0),[a('U',True)],a(type_id),a(value_id),caption,picture_xml.read(None)]
        else:payload=[a(1),a(1),values.read(value_node,namespaces),a(s.ZERO),a(s.ZERO),caption,picture_xml.read(None)]
        result.extend([a(values.native_text(scalar(parts[XR+'Presentation'])),True),[a('#',True),a(data['value_class']),payload]])
        check=scalar(parts[XR+'CheckState'])
        if check not in ('0','1','2'):raise ValueError('Invalid ChoiceList CheckState')
        tails.append([a(check),picture_xml.read(None)])
    result[1]=a(len(tails));result.extend(tails)
    return result
