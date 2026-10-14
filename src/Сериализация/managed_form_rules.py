"""Declarative whole-object property and event rules observed in native exports."""
import copy,json,re
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as E
import metadata_serializer as s


@lru_cache(maxsize=1)
def profiles():
    return json.loads(Path(__file__).with_name('managed_form_rules_851.json').read_text(encoding='utf-8'))['profiles']


def location(entry,path,kind):
    from managed_form_elements import GROUPS,group_children,table_children,form_collection
    node=entry
    for part in path[:-1]:
        if not isinstance(part,int) or not isinstance(node,list) or not 0<=part<len(node):raise ValueError('Unsupported property layout')
        node=node[part]
    part=path[-1]
    if isinstance(part,dict):
        if kind=='Form' and path[:-1]==[1] and set(part)=={'before_controls'}:
            part=form_collection(entry)[0]-part['before_controls']
        elif len(path)==1 and set(part)=={'before_children'} and kind=='Table':
            part=table_children(entry)-part['before_children']
        elif len(path)==1 and set(part)=={'after_children'}:
            index=group_children(entry) if kind in GROUPS else table_children(entry)
            part=index+1+int(s.val(entry[index]))*2+part['after_children']
        else:raise ValueError('Invalid property anchor')
    if not isinstance(node,list) or not isinstance(part,int) or not 0<=part<len(node):raise ValueError('Unsupported property layout')
    return node,part


def put(entry,path,kind,value):
    node,part=location(entry,path,kind);node[part]=copy.deepcopy(value)


def apply_properties(entry,kind,props,namespaces=None,references=None):
    from managed_form_elements import boolean,scalar,title
    rules=profiles()[kind]['properties'];defaults={}
    for rule in rules.values():
        for item in rule['defaults']:
            key=json.dumps(item['path'],sort_keys=True)
            if key in defaults and defaults[key]['value']!=item['value']:raise ValueError('Conflicting native property defaults')
            defaults[key]=item
    # Reset omitted properties as well: XML describes the complete control.
    for item in defaults.values():put(entry,item['path'],kind,s.Parser(item['value']).documents()[0])
    for name,rule in rules.items():
        if name not in props:continue
        node=props[name]
        if rule['codec']=='rich_title':
            from rich_text_xml import title_values
            values=title_values(node)
            for path,value in zip(rule['paths'],values):put(entry,path,kind,value)
            continue
        if rule['codec']=='enum':
            text=scalar(node)
            if text not in rule['values']:raise ValueError('Unsupported '+kind+' '+name+' value: '+text)
            for item in rule['values'][text]:put(entry,item['path'],kind,s.Parser(item['value']).documents()[0])
            continue
        if rule['codec'] in ('color','font','border'):
            import appearance_xml
            value=getattr(appearance_xml,rule['codec'])(node,namespaces)
        elif rule['codec']=='bool':value=boolean(node,False)
        elif rule['codec']=='localized':value=title(node)
        elif rule['codec']=='choice_list':
            import choice_list_xml
            value=choice_list_xml.read(node,namespaces,references)
        elif rule['codec']=='string':value=s.atom(scalar(node),True)
        elif rule['codec']=='int':
            text=scalar(node)
            if not re.fullmatch(r'0|[1-9][0-9]{0,5}',text):raise ValueError('Expected nonnegative form size')
            value=s.atom(text)
        else:raise ValueError('Unsupported property codec')
        for path in rule['paths']:put(entry,path,kind,value)
        for item in rule['fixed']:put(entry,item['path'],kind,s.Parser(item['value']).documents()[0])


def event_names(kind):
    return {name:guid for vector in profiles().get(kind,{}).get('events') or [] for name,guid in vector['names'].items()}


def apply_events(entry,kind,node,materialize_defaults=True):
    from managed_form_elements import Q,events,identifier
    vectors=profiles()[kind].get('events') or [];allowed=event_names(kind);selected={}
    if node is not None:
        if node.attrib:raise ValueError('Unsupported Events attributes')
        for child in node:
            name=child.get('name')
            if child.tag!=Q+'Event' or child.attrib!={'name':name} or len(child) or name not in allowed or name in selected:raise ValueError('Unsupported or duplicate form event')
            selected[name]=identifier(child.text or '')
    if selected and materialize_defaults and profiles()[kind].get('event_header'):
        add_event_defaults(entry,kind,profiles()[kind]['event_header'])
    for vector in vectors:
        subset=E.Element(Q+'Events')
        for name,handler in selected.items():
            if name in vector['names']:E.SubElement(subset,Q+'Event',name=name).text=handler
        parent,index=location(entry,vector['path'],kind)
        parent[index]=events(subset,kind,parent[index],vector['names'])


def add_event_defaults(entry,kind,rule):
    """Native XML loading materializes these defaults alongside event bindings."""
    if kind=='Form':target=entry[1];index=rule['counter']
    else:
        from v8unpack_backend import runtime,to_model
        runtime()
        from v8unpack.helper import calc_offset
        target=entry;index=calc_offset([(4,1),(50,0)],to_model(entry))
    count=int(s.val(target[index]));end=index+1+count*2
    if count<0 or end>len(target):raise ValueError('Invalid event property header')
    values={}
    for i in range(index+1,end,2):
        key=s.val(target[i])
        if key in values:raise ValueError('Duplicate native event property')
        values[key]=target[i+1]
    for key,text in rule['defaults'].items():values.setdefault(key,s.Parser(text).documents()[0])
    replacement=[]
    for key in sorted(values,key=int):replacement.extend([s.atom(key),values[key]])
    target[index]=s.atom(len(values));target[index+1:end]=replacement
