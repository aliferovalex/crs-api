"""Experimental default flat Catalog XML body, verified on 8.5.1.1529."""
import json
import re
import uuid
import xml.etree.ElementTree as E
from pathlib import Path
import comment_serializer as s
import constant_serializer as c
import platform_profiles as platforms


def catalog_xml(text, platform='8.5.1.1529'):
    if not platforms.legacy(platform):raise ValueError('Catalog requires legacy platform profile')
    if not isinstance(text,str) or len(text.encode('utf-8'))>s.MAX_BYTES:raise ValueError('Oversized Catalog XML')
    if '<!DOCTYPE' in text.upper():raise ValueError('DOCTYPE is unsupported')
    top=E.fromstring(text)
    if top.tag!='{%s}MetaDataObject'%c.MD or not platforms.xml_attributes(top.attrib,platform) or len(top)!=1 or top[0].tag!='{%s}Catalog'%c.MD:
        raise ValueError('Expected MetaDataObject/Catalog XML version 2.21')
    obj=top[0]
    if set(obj.attrib)!={'uuid'}:raise ValueError('Unsupported Catalog attributes')
    oid=c.guid(obj.attrib['uuid'])
    permitted={'{%s}%s'%(c.MD,key) for key in ('Properties','InternalInfo','ChildObjects')}
    if len({n.tag for n in obj})!=len(obj) or any(n.tag not in permitted or n.attrib for n in obj):raise ValueError('Unsupported Catalog section')
    child=obj.find('{%s}ChildObjects'%c.MD)
    if child is not None and (len(child) or (child.text or '').strip()):raise ValueError('Catalog children are unsupported')
    props=obj.find('{%s}Properties'%c.MD)
    if props is None or len({n.tag for n in props})!=len(props):raise ValueError('Missing or duplicate Catalog properties')
    fields={n.tag.removeprefix('{%s}'%c.MD):n for n in props}
    if any(n.tag!='{%s}%s'%(c.MD,key) for key,n in fields.items()):raise ValueError('Unexpected property namespace')
    name=fields['Name'].text or ''
    if not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE):raise ValueError('Invalid Catalog name')
    layout=json.loads(Path(__file__).with_name('catalog_layout_851.json').read_text(encoding='utf-8'))
    for key,node in fields.items():
        if node.attrib:raise ValueError('Unsupported Catalog property attributes: '+key)
        if key in ('Synonym','InputByString'):continue
        if len(node):raise ValueError('Unsupported nested Catalog property: '+key)
        if key in ('Name','Comment'):continue
        if key not in layout['defaults'] or (node.text or '')!=layout['defaults'][key]:raise ValueError('Unsupported Catalog property: '+key)
    synonyms=[]
    if 'Synonym' in fields:
        for item in fields['Synonym']:
            if item.tag!='{%s}item'%c.CORE or item.attrib or [n.tag for n in item]!=['{%s}lang'%c.CORE,'{%s}content'%c.CORE] or any(n.attrib or len(n) for n in item):raise ValueError('Unsupported Synonym')
            lang,content=[n.text or '' for n in item]
            if not re.fullmatch('[a-zA-Z][a-zA-Z0-9_-]*',lang) or lang in [p[0] for p in synonyms]:raise ValueError('Invalid or duplicate Synonym language')
            synonyms.append((lang,content))
    if 'InputByString' in fields:
        expected=['Catalog.'+name+'.StandardAttribute.'+v for v in ('Description','Code')]
        node=fields['InputByString']
        if [n.text for n in node]!=expected or any(n.tag!='{%s}Field'%c.READABLE or n.attrib or len(n) for n in node):raise ValueError('Unsupported InputByString')
    docs=s.Parser(layout['template']).documents();native=docs[0][1];common=native[9][1]
    common[1][2]=s.atom(oid);common[2]=s.atom(name,True);common[4]=s.atom(fields['Comment'].text or '' if 'Comment' in fields else '',True)
    common[3]=[s.atom(len(synonyms))]
    for lang,content in synonyms:common[3].extend([s.atom(lang,True),s.atom(content,True)])
    ids=[];internal=obj.find('{%s}InternalInfo'%c.MD)
    if internal is not None:
        categories=('Object','Ref','Selection','List','Manager')
        if len(internal)!=5:raise ValueError('Expected five generated Catalog types')
        for node,category in zip(internal,categories):
            if node.tag!='{%s}GeneratedType'%c.READABLE or node.attrib!={'name':'Catalog'+category+'.'+name,'category':category} or [n.tag for n in node]!=['{%s}TypeId'%c.READABLE,'{%s}ValueId'%c.READABLE] or any(n.attrib or len(n) for n in node):raise ValueError('Unsupported generated Catalog type')
            ids.extend(c.guid(n.text) for n in node)
    else:ids=[str(uuid.uuid4()) for _ in range(10)]
    if len(set(ids+[oid]))!=11:raise ValueError('Duplicate generated Catalog UUID')
    for index,value in zip(list(range(1,9))+[34,35],ids):native[index]=s.atom(value)
    return oid,name,s.native_body_bytes(docs),ids
