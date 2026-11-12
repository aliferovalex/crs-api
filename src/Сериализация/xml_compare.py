"""Compare complete XML trees and validate metadata names."""
import re
from pathlib import Path
import xml_namespaces
import xml_qnames

Q = '{' + xml_namespaces.MD + '}'
PREDEF='{http://v8.1c.ru/8.3/xcf/predef}'


def canonical(node,scopes=None,preserve=False,calculation_predefined=False):
    attributes=dict(node.attrib)
    mode=node.get('{http://www.w3.org/XML/1998/namespace}space')
    if mode is not None:preserve=mode=='preserve'
    text=node.text or ''
    if len(node) and not preserve and not text.strip():text=''
    lexical_namespaces=[]
    if scopes is not None:
        bindings=xml_namespaces.context(scopes,node)
        kind=attributes.get(xml_qnames.XSI+'type')
        if kind is not None:attributes[xml_qnames.XSI+'type']=xml_qnames.qname(kind,bindings)
        if node.tag in ('{'+xml_namespaces.CORE+'}Type','{'+xml_namespaces.CORE+'}TypeSet') or attributes.get(xml_qnames.XSI+'type')==(xml_qnames.XSD,'QName'):
            text=xml_qnames.qname(text,bindings)
        # Schema-specific values (for example style:NormalText) may also use
        # namespace prefixes. Keep their spelling and binding conservatively;
        # only known QName fields above are normalized to expanded names.
        for value in [text,*attributes.values()]:
            if not isinstance(value,str):continue
            match=re.fullmatch(r'([^\W\d][\w.-]*):[^\W\d][\w.-]*',value,re.UNICODE)
            if match:lexical_namespaces.append((value,bindings.get(match[1])))
    ordered=list(node)
    if calculation_predefined and node.tag==PREDEF+'Item' and not preserve:
        # Designer accepts either order of these named sections and emits
        # Base/Leading/Displaced; ibcmd emits Displaced/Base/Leading. Preserve
        # item order, every row within each section, and all other properties.
        slots=[i for i,child in enumerate(ordered) if child.tag in {PREDEF+name for name in ('Base','Leading','Displaced')}]
        sections=[ordered[i] for i in slots]
        if len({child.tag for child in sections})!=len(sections):raise ValueError('Duplicate predefined calculation section')
        for i,child in zip(slots,sorted(sections,key=lambda child:child.tag)):ordered[i]=child
    children=[]
    for child in ordered:
        tail=child.tail or ''
        children.append([canonical(child,scopes,preserve,calculation_predefined),tail if preserve or tail.strip() else ''])
    return [node.tag,attributes,text,children,sorted(lexical_namespaces)]


def document(text):
    """Compare XML structure and QName values using their actual namespaces."""
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise ValueError('DOCTYPE/ENTITY is unsupported in compiler XML')
    root,scopes=xml_namespaces.parse(text)
    kind=root.get(xml_qnames.XSI+'type')
    calculation=(root.tag==PREDEF+'PredefinedData' and kind is not None
                 and xml_qnames.qname(kind,xml_namespaces.context(scopes,root))==(PREDEF[1:-1],'CalculationTypePredefinedItems'))
    return canonical(root,scopes,calculation_predefined=calculation)


def file_equal(name,before,after):
    """Share content equality across planning, CF assembly and reverse checks.

    Raw fingerprints remain separate mutation guards. Binary contents, text
    spaces, XML leaf values and row order are never normalized away here.
    """
    if before==after:return True
    if before is None or after is None:return False
    suffix=Path(name).suffix.lower()
    if suffix not in ('.xml','.bsl','.txt'):return False
    left=before.decode('utf-8-sig').replace('\r\n','\n')
    right=after.decode('utf-8-sig').replace('\r\n','\n')
    return document(left)==document(right) if suffix=='.xml' else left==right


def name_value(node):
    if node is None or node.attrib or len(node) or not re.fullmatch(r'[^\W\d]\w{0,79}', node.text or '', re.UNICODE):
        raise ValueError('Invalid metadata Name')
    return node.text
