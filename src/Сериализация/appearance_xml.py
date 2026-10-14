"""Native color and font values shared by all mapped control properties."""
import json,re
from decimal import Decimal,InvalidOperation
from functools import lru_cache
from io import StringIO
from pathlib import Path
from xml.etree import ElementTree as E
import metadata_serializer as s


@lru_cache(maxsize=1)
def profile():
    return json.loads(Path(__file__).with_name('appearance_layout_851.json').read_text(encoding='utf-8'))


def namespaces(xml):
    result={}
    for _,(prefix,uri) in E.iterparse(StringIO(xml),events=('start-ns',)):
        if prefix in result and result[prefix]!=uri:raise ValueError('Ambiguous appearance namespace prefix')
        result[prefix]=uri
    return result


def reference(text,bindings):
    parts=text.split(':')
    if len(parts)!=2 or not parts[0] or not parts[1] or parts[0] not in (bindings or {}):raise ValueError('Unbound appearance reference: '+text)
    return bindings[parts[0]],parts[1]


def color(node,bindings):
    if node.attrib or len(node):raise ValueError('Unsupported Color XML')
    text=node.text or ''
    if re.fullmatch(r'#[0-9a-fA-F]{6}',text):
        red,green,blue=(int(text[i:i+2],16) for i in (1,3,5))
        return s.Parser(profile()['color']['rgb_template'].replace('RGB_VALUE',str(red+(green<<8)+(blue<<16)))).documents()[0]
    uri,name=reference(text,bindings)
    native=profile()['color']['references'].get(uri,{}).get(name)
    if native is None:raise ValueError('Unsupported or unverified color reference: '+text)
    return s.Parser(native).documents()[0]


def font(node,bindings):
    if len(node) or (node.text or '').strip():raise ValueError('Unsupported Font XML')
    data=profile()['font'];attrs=node.attrib
    if not attrs:return s.Parser(data['inherit_template']).documents()[0]
    allowed=set(data['bits'])|{'ref','kind'}
    if set(attrs)-allowed:raise ValueError('Unsupported Font attribute')
    kind=attrs.get('kind');values={};flags=0
    for name,bit in data['bits'].items():
        if name not in attrs:continue
        text=attrs[name]
        if name=='faceName':
            if not text or len(text)>128 or any(c in text for c in '\0\r\n'):raise ValueError('Invalid font faceName')
            value=s.atom(text,True)
        elif name=='height':
            if not re.fullmatch(r'[0-9]+(?:\.[0-9])?',text):raise ValueError('Font height requires at most one decimal place')
            try:height=Decimal(text)
            except InvalidOperation:raise ValueError('Invalid font height') from None
            if height>1000:raise ValueError('Font height exceeds supported range')
            value=s.atom(int(height*10))
        else:
            if text not in ('true','false'):raise ValueError('Invalid font '+name)
            value=s.atom((700 if text=='true' else 400) if name=='bold' else (1 if text=='true' else 0))
        flags|=bit;values[name]=value
    if kind=='Absolute':
        if 'ref' in attrs or 'faceName' not in values:raise ValueError('Absolute font requires faceName and no ref')
        result=s.Parser(data['absolute_template']).documents()[0];result[data['flags_slot']]=s.atom(flags)
        for name,value in values.items():result[data['absolute_slots'][name]]=value
        return result
    if kind=='StyleItem':
        if 'ref' not in attrs or 'faceName' in values:raise ValueError('Style font requires ref and no faceName override')
        uri,name=reference(attrs['ref'],bindings);native=data['references'].get(uri,{}).get(name)
        if native is None:raise ValueError('Unsupported or unverified font reference')
        result=[s.atom(data['version']),s.atom(data['style_kind']),s.atom(flags),s.Parser(native).documents()[0]]
        for name in data['style_order']:
            if name in values:result.append(values[name])
        result.extend(s.Parser(data['scale_tail']).documents()[0]);return result
    raise ValueError('Unsupported font kind')


def border(node,bindings):
    data=profile()['border']
    if set(node.attrib)-{'width','ref'} or (node.text or '').strip() or len(node)>1:raise ValueError('Unsupported Border XML')
    width=node.get('width','0')
    if not re.fullmatch(r'0|[1-9][0-9]{0,5}',width):raise ValueError('Expected nonnegative border width')
    if 'ref' in node.attrib:
        if len(node):raise ValueError('Border ref with explicit style is not supported')
        uri,name=reference(node.get('ref'),bindings);native=data['references'].get(uri,{}).get(name)
        if native is None:raise ValueError('Unsupported or unverified border reference')
        result=s.Parser(data['reference_template']).documents()[0];result[data['reference_slot']]=s.Parser(native).documents()[0]
    else:result=s.Parser(data['template']).documents()[0]
    result[data['width_slot']]=s.atom(width)
    if len(node):
        child=node[0];type_key='{http://www.w3.org/2001/XMLSchema-instance}type'
        if child.tag!='{http://v8.1c.ru/8.1/data/ui}style' or set(child.attrib)!={type_key} or len(child) or (child.tail or '').strip():raise ValueError('Unsupported border style XML')
        if reference(child.get(type_key),bindings)!=('http://v8.1c.ru/8.1/data/ui','ControlBorderType'):raise ValueError('Unsupported border style type')
        name=child.text or ''
        if name not in data['styles']:raise ValueError('Unsupported border style: '+name)
        result[data['style_slot']]=s.atom(data['styles'][name]);result[data['type_slot']]=s.atom(data['control_type_id'])
    return result
