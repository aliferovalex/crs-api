"""Resolve XML QName values."""

XSI='{http://www.w3.org/2001/XMLSchema-instance}'
XSD='http://www.w3.org/2001/XMLSchema'


def qname(text,namespaces):
    parts=text.split(':')
    if len(parts)==1:prefix,name='',parts[0]
    elif len(parts)==2:prefix,name=parts
    else:raise ValueError('Invalid XML type QName')
    if not name or prefix not in (namespaces or {}):raise ValueError('Unbound XML type QName: '+text)
    return namespaces[prefix],name
