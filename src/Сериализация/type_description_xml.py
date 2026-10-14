"""Verified scalar Type XML <-> native Pattern conversion (8.5.1 profile)."""
from xml.etree import ElementTree as E
import metadata_serializer as s

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
        if not 1<=length<=1024 or allowed!='Variable':raise ValueError('Only variable strings of length 1..1024 are supported')
        value=[a('S',True),a(length),a(1)]
    elif kind=='xs:decimal':
        digits,fraction,sign=qualifiers('NumberQualifiers',['Digits','FractionDigits','AllowedSign'])
        digits,fraction=int(digits),int(fraction)
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
    if values[0]=='S' and len(values)==3 and values[2]=='1':
        E.SubElement(result,Q+'Type').text='xs:string';fields('StringQualifiers',[('Length',values[1]),('AllowedLength','Variable')])
    elif values[0]=='N' and len(values)==4 and values[3] in ('0','1'):
        E.SubElement(result,Q+'Type').text='xs:decimal';fields('NumberQualifiers',[('Digits',values[1]),('FractionDigits',values[2]),('AllowedSign','Any' if values[3]=='0' else 'Nonnegative')])
    elif values==['B']:E.SubElement(result,Q+'Type').text='xs:boolean'
    elif values in (['D'],['D','D'],['D','T']):
        E.SubElement(result,Q+'Type').text='xs:dateTime';fields('DateQualifiers',[('DateFractions','DateTime' if len(values)==1 else ('Date' if values[1]=='D' else 'Time'))])
    else:raise ValueError('Unsupported native scalar Type')
    if s.render(read(result))!=s.render(pattern):raise ValueError('Native Type is outside the verified qualifier profile')
    return result
