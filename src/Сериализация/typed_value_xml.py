"""Verified scalar xsi:type values for reusable native value codecs."""
import re
from datetime import datetime
from decimal import Decimal
import metadata_serializer as s

XSI='{http://www.w3.org/2001/XMLSchema-instance}'
XSD='http://www.w3.org/2001/XMLSchema'


def native_text(text):
    """Native quoted text inserts CR before each logical LF (verified on 8.5.1)."""
    return text.replace('\n','\r\n')


def qname(text,namespaces):
    parts=text.split(':')
    if len(parts)==1:prefix,name='',parts[0]
    elif len(parts)==2:prefix,name=parts
    else:raise ValueError('Invalid XML type QName')
    if not name or prefix not in (namespaces or {}):raise ValueError('Unbound XML type QName: '+text)
    return namespaces[prefix],name


def read(node,namespaces):
    if node is None or set(node.attrib)!={XSI+'type'} or len(node):raise ValueError('Expected scalar typed XML value')
    uri,kind=qname(node.get(XSI+'type'),namespaces)
    if uri!=XSD:raise ValueError('Unsupported value namespace: '+uri)
    value=node.text or '';a=s.atom
    if kind=='string':return [a('S',True),a(native_text(value),True)]
    if kind=='decimal':
        if not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)',value):raise ValueError('Invalid decimal value')
        number=Decimal(value)
        if len(number.as_tuple().digits)>38:raise ValueError('Decimal value exceeds 38 digits')
        text=format(number,'f')
        if '.' in text:text=text.rstrip('0').rstrip('.')
        if number==0:text='0'
        return [a('N',True),a(text)]
    if kind=='boolean':
        if value not in ('true','false'):raise ValueError('Expected true/false scalar value')
        return [a('B',True),a(1 if value=='true' else 0)]
    if kind=='dateTime':
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}',value):raise ValueError('Expected dateTime without timezone or fractions')
        date=datetime.strptime(value,'%Y-%m-%dT%H:%M:%S')
        text=f'{date.year:04d}{date.month:02d}{date.day:02d}{date.hour:02d}{date.minute:02d}{date.second:02d}'
        return [a('D',True),a(text)]
    raise ValueError('Unsupported scalar value type: '+kind)
