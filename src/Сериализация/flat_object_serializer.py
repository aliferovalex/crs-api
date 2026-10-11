"""Shared strict XML reader for Catalog, Document, inline Enum and CommonModule bodies."""
import json
import re
import uuid
import xml.etree.ElementTree as E
from pathlib import Path
import comment_serializer as s
import constant_serializer as c
import platform_profiles as platforms


def object_xml(text, platform, kind):
    if kind not in ('Catalog','Document','Enum','CommonModule'):raise ValueError('Unsupported flat object kind')
    if not platforms.legacy(platform):raise ValueError(kind+' requires legacy platform profile')
    if not isinstance(text,str) or len(text.encode('utf-8'))>s.MAX_BYTES:raise ValueError(f'Oversized {kind} XML')
    if '<!DOCTYPE' in text.upper():raise ValueError('DOCTYPE is unsupported')
    top=E.fromstring(text)
    if top.tag!='{%s}MetaDataObject'%c.MD or not platforms.xml_attributes(top.attrib,platform) or len(top)!=1 or top[0].tag!='{%s}%s'%(c.MD,kind):
        raise ValueError(f'Expected MetaDataObject/{kind} XML with a legacy XML version')
    obj=top[0]
    if set(obj.attrib)!={'uuid'}:raise ValueError(f'Unsupported {kind} attributes')
    oid=c.guid(obj.attrib['uuid'])
    permitted={'{%s}%s'%(c.MD,key) for key in ('Properties','InternalInfo','ChildObjects')}
    if len({n.tag for n in obj})!=len(obj) or any(n.tag not in permitted or n.attrib for n in obj):raise ValueError(f'Unsupported {kind} section')
    child=obj.find('{%s}ChildObjects'%c.MD)
    if kind != 'Enum' and child is not None and (len(child) or (child.text or '').strip()):raise ValueError(f'{kind} children are unsupported')
    props=obj.find('{%s}Properties'%c.MD)
    if props is None or len({n.tag for n in props})!=len(props):raise ValueError(f'Missing or duplicate {kind} properties')
    fields={n.tag.removeprefix('{%s}'%c.MD):n for n in props}
    if any(n.tag!='{%s}%s'%(c.MD,key) for key,n in fields.items()):raise ValueError('Unexpected property namespace')
    name=fields['Name'].text or ''
    if not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE):raise ValueError(f'Invalid {kind} name')
    layout=json.loads(Path(__file__).with_name(kind.lower()+'_layout_851.json').read_text(encoding='utf-8'))
    for key,node in fields.items():
        if node.attrib:raise ValueError(f'Unsupported {kind} property attributes: '+key)
        if key=='InputByString' and not layout['input_fields']:raise ValueError(f'Unsupported {kind} property: '+key)
        if key in ('Synonym','InputByString'):continue
        if len(node):raise ValueError(f'Unsupported nested {kind} property: '+key)
        if key in ('Name','Comment'):continue
        if key not in layout['defaults'] or (node.text or '')!=layout['defaults'][key]:raise ValueError(f'Unsupported {kind} property: '+key)
    synonyms=[]
    if 'Synonym' in fields:
        for item in fields['Synonym']:
            if item.tag!='{%s}item'%c.CORE or item.attrib or [n.tag for n in item]!=['{%s}lang'%c.CORE,'{%s}content'%c.CORE] or any(n.attrib or len(n) for n in item):raise ValueError('Unsupported Synonym')
            lang,content=[n.text or '' for n in item]
            if not re.fullmatch('[a-zA-Z][a-zA-Z0-9_-]*',lang) or lang in [p[0] for p in synonyms]:raise ValueError('Invalid or duplicate Synonym language')
            synonyms.append((lang,content))
    if 'InputByString' in fields:
        expected=[kind+'.'+name+'.StandardAttribute.'+v for v in layout['input_fields']]
        node=fields['InputByString']
        if [n.text for n in node]!=expected or any(n.tag!='{%s}Field'%c.READABLE or n.attrib or len(n) for n in node):raise ValueError('Unsupported InputByString')
    docs=s.Parser(layout['template']).documents();native=docs[0][1];common=native[layout.get('common_slot',9)]
    if not layout.get('common_direct'):common=common[1]
    common[1][2]=s.atom(oid);common[2]=s.atom(name,True);common[4]=s.atom(fields['Comment'].text or '' if 'Comment' in fields else '',True)
    common[3]=[s.atom(len(synonyms))]
    for lang,content in synonyms:common[3].extend([s.atom(lang,True),s.atom(content,True)])
    ids=[];internal=obj.find('{%s}InternalInfo'%c.MD)
    if internal is not None:
        categories=layout.get('generated_categories',('Object','Ref','Selection','List','Manager'))
        if len(internal)!=len(categories):raise ValueError(f'Expected {len(categories)} generated {kind} types')
        for node,category in zip(internal,categories):
            if node.tag!='{%s}GeneratedType'%c.READABLE or node.attrib!={'name':kind+category+'.'+name,'category':category} or [n.tag for n in node]!=['{%s}TypeId'%c.READABLE,'{%s}ValueId'%c.READABLE] or any(n.attrib or len(n) for n in node):raise ValueError(f'Unsupported generated {kind} type')
            ids.extend(c.guid(n.text) for n in node)
    else:ids=[str(uuid.uuid4()) for _ in layout['generated_slots']]
    if len(set(ids+[oid]))!=len(ids)+1:raise ValueError(f'Duplicate generated {kind} UUID')
    for index,value in zip(layout['generated_slots'],ids):native[index]=s.atom(value)
    object_name=name
    if kind == 'Enum':
        value_ids=[];names=set();row=docs[0][layout['values_slot']]
        if child is not None:
            if (child.text or '').strip() or len(child)>1024:raise ValueError('Invalid Enum values')
            for value in child:
                if value.tag!='{%s}EnumValue'%c.MD or set(value.attrib)!={'uuid'} or len(value)!=1 or value[0].tag!='{%s}Properties'%c.MD:
                    raise ValueError('Only inline EnumValue properties are supported')
                vid=c.guid(value.get('uuid'));props=value[0]
                if props.attrib or len({p.tag for p in props})!=len(props):raise ValueError('Invalid EnumValue properties')
                fields={p.tag.removeprefix('{%s}'%c.MD):p for p in props}
                if any(p.tag!='{%s}%s'%(c.MD,k) or p.attrib for k,p in fields.items()):raise ValueError('Invalid EnumValue property')
                for key,node in fields.items():
                    if key not in ('Name','Synonym','Comment','Color') or (key!='Synonym' and len(node)):
                        raise ValueError('Unsupported EnumValue property: '+key)
                name=fields['Name'].text or ''
                if not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE) or name.casefold() in names:raise ValueError('Invalid or duplicate EnumValue name')
                names.add(name.casefold())
                if 'Color' in fields and fields['Color'].text!='auto':raise ValueError('Only auto EnumValue color is supported')
                entry=s.Parser(layout['value_template']).documents()[0];common=entry[0][1]
                common[1][2]=s.atom(vid);common[2]=s.atom(name,True);common[4]=s.atom(fields['Comment'].text or '' if 'Comment' in fields else '',True)
                synonyms=[]
                if 'Synonym' in fields:
                    for item in fields['Synonym']:
                        if item.tag!='{%s}item'%c.CORE or item.attrib or [p.tag for p in item]!=['{%s}lang'%c.CORE,'{%s}content'%c.CORE] or any(p.attrib or len(p) for p in item):raise ValueError('Unsupported EnumValue Synonym')
                        lang,content=[p.text or '' for p in item]
                        if not re.fullmatch('[a-zA-Z][a-zA-Z0-9_-]*',lang) or lang in [p[0] for p in synonyms]:raise ValueError('Invalid EnumValue Synonym language')
                        synonyms.append((lang,content))
                common[3]=[s.atom(len(synonyms))]
                for lang,content in synonyms:common[3].extend([s.atom(lang,True),s.atom(content,True)])
                row.append(entry);value_ids.append(vid)
        if len(set(ids+[oid]+value_ids))!=len(ids)+1+len(value_ids):raise ValueError('Duplicate EnumValue UUID')
        row[1]=s.atom(len(value_ids));ids+=value_ids
    return oid,object_name,s.native_body_bytes(docs),ids
