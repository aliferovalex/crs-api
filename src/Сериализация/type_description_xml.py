"""Verified scalar Type XML <-> native Pattern conversion (8.5.1 profile)."""
from xml.etree import ElementTree as E
import uuid
import native_metadata as s
import metadata_type_sets as type_sets

Q='{http://v8.1c.ru/8.1/data/core}'


def text(node):
    if node.attrib or len(node):raise ValueError('Unsupported Type structure')
    return node.text or ''


def read(node):
    if node is None or node.attrib or not len(node) or node[0].tag!=Q+'Type':raise ValueError('Expected a scalar Type description')
    kind=text(node[0]);a=s.atom
    def qualifiers(name,keys):
        if len(node)!=2 or node[1].tag!=Q+name or node[1].attrib or [n.tag for n in node[1]]!=[Q+k for k in keys]:raise ValueError('Unsupported type qualifiers')
        return [text(n) for n in node[1]]
    if kind=='xs:string':
        length,allowed=qualifiers('StringQualifiers',['Length','AllowedLength'])
        length=int(length)
        if allowed=='Variable' and 0<=length<=1024:
            value=[a('S',True)] if length==0 else [a('S',True),a(length),a(1)]
        elif allowed=='Fixed' and 1<=length<=100:
            value=[a('S',True),a(length),a(0)]
        else:raise ValueError('Invalid String qualifiers: variable length 0..1024 or fixed length 1..100 required')
    elif kind=='xs:decimal':
        digits,fraction,sign=qualifiers('NumberQualifiers',['Digits','FractionDigits','AllowedSign'])
        digits,fraction=int(digits),int(fraction)
        if digits==0 and fraction==0 and sign=='Any':value=[a('N',True)]
        else:
            if not 1<=digits<=38 or not 0<=fraction<=digits or sign not in ('Any','Nonnegative'):raise ValueError('Invalid Number qualifiers')
            value=[a('N',True),a(digits),a(fraction),a(0 if sign=='Any' else 1)]
    elif kind=='xs:boolean':
        if len(node)!=1:raise ValueError('Boolean qualifiers are unsupported')
        value=[a('B',True)]
    elif kind=='xs:dateTime':
        fractions,=qualifiers('DateQualifiers',['DateFractions'])
        if fractions not in ('DateTime','Date','Time'):raise ValueError('Invalid Date fractions')
        value=[a('D',True)]+([] if fractions=='DateTime' else [a('D' if fractions=='Date' else 'T',True)])
    else:raise ValueError('Unsupported Type: '+kind)
    return [a('Pattern',True),value]


def export(pattern,tag):
    if not isinstance(pattern,list) or len(pattern)!=2 or s.val(pattern[0])!='Pattern' or not isinstance(pattern[1],list):raise ValueError('Unsupported native Type pattern')
    values=[s.val(v) for v in pattern[1]]
    if not values:raise ValueError('Empty native Type')
    result=E.Element(tag)
    def fields(name,items):
        parent=E.SubElement(result,Q+name)
        for key,value in items:E.SubElement(parent,Q+key).text=value
    if values==['S']:
        E.SubElement(result,Q+'Type').text='xs:string';fields('StringQualifiers',[('Length','0'),('AllowedLength','Variable')])
    elif values==['N']:
        E.SubElement(result,Q+'Type').text='xs:decimal';fields('NumberQualifiers',[('Digits','0'),('FractionDigits','0'),('AllowedSign','Any')])
    elif values[0]=='S' and len(values)==3 and values[2] in ('0','1'):
        E.SubElement(result,Q+'Type').text='xs:string';fields('StringQualifiers',[('Length',values[1]),('AllowedLength','Variable' if values[2]=='1' else 'Fixed')])
    elif values[0]=='N' and len(values)==4 and values[3] in ('0','1'):
        E.SubElement(result,Q+'Type').text='xs:decimal';fields('NumberQualifiers',[('Digits',values[1]),('FractionDigits',values[2]),('AllowedSign','Any' if values[3]=='0' else 'Nonnegative')])
    elif values==['B']:E.SubElement(result,Q+'Type').text='xs:boolean'
    elif values in (['D'],['D','D'],['D','T']):
        E.SubElement(result,Q+'Type').text='xs:dateTime';fields('DateQualifiers',[('DateFractions','DateTime' if len(values)==1 else ('Date' if values[1]=='D' else 'Time'))])
    else:raise ValueError('Unsupported native scalar Type')
    if s.render(read(result))!=s.render(pattern):raise ValueError('Native Type is outside the verified qualifier profile')
    return result


def read_form(node,references=None):
    """Read a complete form type without widening other metadata profiles."""
    if node is None or node.attrib or not len(node):raise ValueError('Expected form Type description')
    kinds=[];qualifiers={}
    qualifier_names={'xs:string':'StringQualifiers','xs:decimal':'NumberQualifiers','xs:dateTime':'DateQualifiers'}
    for child in node:
        if child.tag in (Q+'Type',Q+'TypeSet'):
            kind=text(child)
            if (child.tag==Q+'TypeSet')!=type_sets.is_set(kind):
                raise ValueError('TypeSet requires a verified group or defined type reference')
            if kind in kinds:raise ValueError('Duplicate form Type')
            kinds.append(kind)
        elif child.tag in {Q+name for name in qualifier_names.values()}:
            if child.tag in qualifiers:raise ValueError('Duplicate form type qualifiers')
            qualifiers[child.tag]=child
        else:raise ValueError('Unsupported form Type structure')
    if not kinds or len(kinds)>256:raise ValueError('Invalid form Type count')
    used=set();patterns=[];reference_ids=set()
    for kind in kinds:
        if kind.startswith('cfg:'):
            value=type_sets.references(references).get(kind)
            if not isinstance(value,str):raise ValueError('Unresolved form reference type: '+kind)
            value=str(uuid.UUID(value))
            if value==s.ZERO or value in reference_ids:raise ValueError('Duplicate or empty generated reference type')
            reference_ids.add(value);patterns.append([s.atom('#',True),s.atom(value)])
            continue
        single=E.Element(node.tag);E.SubElement(single,Q+'Type').text=kind
        qualifier=qualifier_names.get(kind)
        if qualifier is not None and Q+qualifier in qualifiers:
            single.append(qualifiers[Q+qualifier]);used.add(Q+qualifier)
        patterns.append(read(single)[1])
    if used!=set(qualifiers):raise ValueError('Qualifiers do not belong to any form Type')
    order={'B':0,'S':1,'D':2,'N':3,'#':4}
    patterns.sort(key=lambda p:(order[s.val(p[0])],s.val(p[1]) if s.val(p[0])=='#' else ''))
    return [s.atom('Pattern',True)]+patterns


def read_metadata(node,references=None):
    """Metadata and form properties share the native Pattern representation."""
    return read_form(node,references)


def export_metadata(pattern,tag,references=None):
    if not isinstance(pattern,list) or len(pattern)<2 or s.val(pattern[0])!='Pattern':raise ValueError('Unsupported native Type pattern')
    reverse={}
    for name,value in type_sets.references(references).items():
        key=str(uuid.UUID(value))
        if key in reverse:raise ValueError('Ambiguous generated type XML name')
        reverse[key]=name
    result=E.Element(tag);qualifiers=[]
    for arm in pattern[1:]:
        if not isinstance(arm,list) or not arm:raise ValueError('Invalid native Type arm')
        if s.val(arm[0])=='#':
            if len(arm)!=2 or s.val(arm[1]) not in reverse:raise ValueError('Unresolved native metadata reference type')
            name=reverse[s.val(arm[1])]
            E.SubElement(result,Q+('TypeSet' if type_sets.is_set(name) else 'Type')).text=name
        else:
            scalar=export([s.atom('Pattern',True),arm],tag)
            result.append(scalar[0]);qualifiers.extend(list(scalar)[1:])
    result.extend(qualifiers)
    if s.render(read_metadata(result,references))!=s.render(pattern):raise ValueError('Native Type pattern is not canonical')
    return result
