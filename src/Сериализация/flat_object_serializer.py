"""Shared strict XML reader driven by verified native object profiles."""
import json
import re
import uuid
import xml.etree.ElementTree as E
from pathlib import Path
import metadata_serializer as s
import constant_serializer as c
import platform_profiles as platforms
import object_xml_profiles as profiles
import type_description_xml as types
import metadata_localized_xml as localized


def object_xml(text, platform, kind,objects=None):
    if kind not in profiles.profiles():raise ValueError('Unsupported flat object kind')
    if not platforms.legacy(platform):raise ValueError(kind+' requires legacy platform profile')
    if not isinstance(text,str) or len(text.encode('utf-8'))>s.MAX_BYTES:raise ValueError(f'Oversized {kind} XML')
    if '<!DOCTYPE' in text.upper():raise ValueError('DOCTYPE is unsupported')
    try:top=E.fromstring(text)
    except E.ParseError as error:raise ValueError('Invalid object XML: '+str(error)) from None
    if top.tag!='{%s}MetaDataObject'%c.MD or not platforms.xml_attributes(top.attrib,platform) or len(top)!=1 or top[0].tag!='{%s}%s'%(c.MD,kind):
        raise ValueError(f'Expected MetaDataObject/{kind} XML with a legacy XML version')
    obj=top[0]
    if set(obj.attrib)!={'uuid'}:raise ValueError(f'Unsupported {kind} attributes')
    oid=c.guid(obj.attrib['uuid'])
    layout=json.loads(Path(__file__).with_name(kind.lower()+'_layout_851.json').read_text(encoding='utf-8'))
    permitted={'{%s}%s'%(c.MD,key) for key in ('Properties','InternalInfo','ChildObjects')}
    if len({n.tag for n in obj})!=len(obj) or any(n.tag not in permitted or n.attrib for n in obj):raise ValueError(f'Unsupported {kind} section')
    child=obj.find('{%s}ChildObjects'%c.MD)
    if kind != 'Enum' and not layout.get('inline_collections') and not layout.get('tabular_collections') and not layout.get('child_collections') and child is not None and (len(child) or (child.text or '').strip()):raise ValueError(f'{kind} children are unsupported')
    props=obj.find('{%s}Properties'%c.MD)
    if props is None or len({n.tag for n in props})!=len(props):raise ValueError(f'Missing or duplicate {kind} properties')
    fields={n.tag.removeprefix('{%s}'%c.MD):n for n in props}
    if any(n.tag!='{%s}%s'%(c.MD,key) for key,n in fields.items()):raise ValueError('Unexpected property namespace')
    name=fields['Name'].text or ''
    if not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE):raise ValueError(f'Invalid {kind} name')
    for key,node in fields.items():
        if node.attrib:raise ValueError(f'Unsupported {kind} property attributes: '+key)
        if key=='InputByString' and not layout['input_fields']:raise ValueError(f'Unsupported {kind} property: '+key)
        if key in ('Synonym','InputByString'):continue
        if key in layout.get('localized_properties',{}):continue
        if key in layout.get('reference_lists',{}):continue
        if key in layout.get('reference_values',{}):continue
        if key=='Type' and 'type_path' in layout:continue
        if key in layout.get('scalar_properties',{}):
            if len(node) or (node.text or '') not in layout['scalar_properties'][key]['values']:
                raise ValueError('Unsupported '+kind+' property value: '+key)
            continue
        if key in layout.get('string_slots',{}):
            if len(node) or not node.text or '\0' in node.text:raise ValueError('Invalid '+kind+' property: '+key)
            continue
        if len(node):raise ValueError(f'Unsupported nested {kind} property: '+key)
        if key in ('Name','Comment'):continue
        if key not in layout['defaults'] or (node.text or '')!=layout['defaults'][key]:raise ValueError(f'Unsupported {kind} property: '+key)
    synonyms=localized.read(fields.get('Synonym'),'Synonym')
    if 'InputByString' in fields:
        expected=[kind+'.'+name+'.StandardAttribute.'+v for v in layout['input_fields']]
        node=fields['InputByString']
        if [n.text for n in node]!=expected or any(n.tag!='{%s}Field'%c.READABLE or n.attrib or len(n) for n in node):raise ValueError('Unsupported InputByString')
    docs=s.Parser(layout['template']).documents();native=docs[0][1]
    if 'common_path' in layout:
        common=docs[0]
        for slot in layout['common_path']:common=common[slot]
    else:
        common=native[layout.get('common_slot',9)]
        if not layout.get('common_direct'):common=common[1]
    common[1][2]=s.atom(oid);common[2]=s.atom(name,True);common[4]=s.atom(fields['Comment'].text or '' if 'Comment' in fields else '',True)
    common[3]=synonyms
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
    for key,profile in layout.get('scalar_properties',{}).items():
        if key not in fields:continue
        node=docs[0]
        for slot in profile['path'][:-1]:node=node[slot]
        node[profile['path'][-1]]=s.atom(profile['values'][fields[key].text or ''])
    for key,path in layout.get('localized_properties',{}).items():
        node=docs[0]
        for slot in path[:-1]:node=node[slot]
        node[path[-1]]=localized.read(fields.get(key),key)
    for key,profile in layout.get('reference_values',{}).items():
        field=fields.get(key)
        if field is None or not (field.text or ''):
            if profile.get('required'):raise ValueError('Required metadata reference: '+key)
            value=s.ZERO
        else:
            if field.attrib or len(field):raise ValueError('Invalid metadata reference: '+key)
            wrapper=E.Element('References');E.SubElement(wrapper,'{'+c.READABLE+'}Item').text=field.text
            value=reference_ids(wrapper,profile,objects or {},oid)[0]
        node=docs[0]
        for slot in profile['path'][:-1]:node=node[slot]
        node[profile['path'][-1]]=s.atom(value)
    for key,profile in layout.get('reference_lists',{}).items():
        values=reference_ids(fields.get(key),profile,objects or {})
        node=docs[0]
        for slot in profile['path'][:-1]:node=node[slot]
        row=[s.atom(0),s.atom(len(values))]
        for oid_value in values:
            item=s.Parser(profile['item_template']).documents()[0];target=item
            for slot in profile['id_path'][:-1]:target=target[slot]
            target[profile['id_path'][-1]]=s.atom(oid_value);row.append(item)
        node[profile['path'][-1]]=row
    for key,path in layout.get('string_slots',{}).items():
        if key not in fields:raise ValueError('Required '+kind+' property: '+key)
        node=docs[0]
        for slot in path[:-1]:node=node[slot]
        node[path[-1]]=s.atom(fields[key].text,True)
    if 'type_path' in layout and 'Type' in fields:
        node=docs[0];path=layout['type_path']
        for slot in path[:-1]:node=node[slot]
        node[path[-1]]=types.read(fields['Type'])
    object_name=name
    if layout.get('inline_collections') or layout.get('tabular_collections') or layout.get('child_collections') or layout.get('command_collections'):
        import inline_object_xml as inline
        names=set();command_names=set();feature_ids=[]
        for n in ([] if child is None else child):
            key=n.tag.removeprefix('{'+c.MD+'}')
            if n.tag!='{'+c.MD+'}'+key:raise ValueError('Unsupported inline namespace')
            if key in layout.get('child_collections',{}):
                import child_object_xml as child_xml
                profile=layout['child_collections'][key];child_id=child_xml.resolve(n,profile,oid,objects or {})
                row=docs[0][profile['slot']]
                if child_id in [s.val(key) for key in row[2:]]:raise ValueError('Duplicate child object reference')
                row.append(s.atom(child_id));row[1]=s.atom(len(row)-2)
                continue
            generated=[]
            name_scope=names
            if key in layout.get('command_collections',{}):
                import inline_command_xml as commands
                profile=layout['command_collections'][key];aid,aname,entry=commands.read(n,profile);new_features=[aid];name_scope=command_names
            elif key in layout.get('tabular_collections',{}):
                import catalog_tabular_xml as tabular
                profile=layout['tabular_collections'][key];aid,aname,entry,new_features,generated=tabular.read(n,object_name,kind=profile['kind'])
            elif key in layout.get('inline_collections',{}):
                profile=layout['inline_collections'][key];aid,aname,entry=inline.read(n,profile);new_features=[aid]
            else:raise ValueError('Unsupported inline child: '+key)
            if set(new_features+generated)&set(ids+[oid]+feature_ids) or aname.casefold() in name_scope:raise ValueError('Duplicate inline UUID or name')
            feature_ids+=new_features;ids+=generated;name_scope.add(aname.casefold());row=docs[0][profile['slot']];row.append(entry);row[1]=s.atom(len(row)-2)
        if child is not None and ((child.text or '').strip() or any((n.tail or '').strip() for n in child)):raise ValueError('Unsupported inline collection text')
        ids+=feature_ids
    if kind == 'Enum':
        value_ids=[];names=set();row=docs[0][layout['values_slot']]
        import appearance_xml as appearance
        bindings=None
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
                entry=s.Parser(layout['value_template']).documents()[0];common=entry[0][1]
                if 'Color' in fields and fields['Color'].text!='auto':
                    if bindings is None:bindings=appearance.namespaces(text)
                    color=entry
                    for slot in layout['value_color_path'][:-1]:color=color[slot]
                    color[layout['value_color_path'][-1]]=appearance.color(fields['Color'],bindings)
                common[1][2]=s.atom(vid);common[2]=s.atom(name,True);common[4]=s.atom(fields['Comment'].text or '' if 'Comment' in fields else '',True)
                common[3]=localized.read(fields.get('Synonym'),'EnumValue Synonym')
                row.append(entry);value_ids.append(vid)
        if len(set(ids+[oid]+value_ids))!=len(ids)+1+len(value_ids):raise ValueError('Duplicate EnumValue UUID')
        row[1]=s.atom(len(value_ids));ids+=value_ids
    return oid,object_name,s.native_body_bytes(docs),ids


def reference_ids(node,profile,objects,owner=None):
    targets=profile['target'] if isinstance(profile['target'],list) else [profile['target']]
    if node is None or not len(node):
        if profile.get('required'):raise ValueError('Required reference list: '+','.join(targets))
        return []
    if node.attrib or (node.text or '').strip():raise ValueError('Invalid reference list')
    result=[]
    for item in node:
        if item.tag!='{'+c.READABLE+'}Item' or len(item) or item.attrib not in ({},{'{http://www.w3.org/2001/XMLSchema-instance}type':'xr:MDObjectRef'}):raise ValueError('Unsupported metadata reference')
        text=item.text or ''
        if profile.get('owner_kind'):
            parts=text.split('.')
            child_tag=profile.get('owned_tag','Form');label='form' if child_tag=='Form' else 'child'
            if len(parts)!=4 or parts[0]!=profile['owner_kind'] or parts[2]!=child_tag or not parts[1] or not parts[3] or (item.tail or '').strip():raise ValueError('Invalid owned '+label+' reference')
            owners=[oid for oid,d in objects.items() if s.val(d[0][2])==c.identifiers.class_id(parts[0]) and s.val(d[0][9])==parts[1] and (owner is None or oid==owner)]
            if len(owners)!=1:raise ValueError('Missing, ambiguous or foreign '+label+' owner')
            owner_id=owners[0]
            matches=[oid for oid,d in objects.items() if s.val(d[0][2]) in {c.identifiers.class_id(kind) for kind in targets} and s.val(d[0][3])==owner_id and s.val(d[0][9])==parts[3] and s.val(d[0][4])==s.ZERO]
            if len(matches)!=1 or matches[0] in result or (matches[0],s.val(objects[matches[0]][0][2])) not in c.children(objects[owner_id][0]):raise ValueError('Missing, ambiguous or unregistered owned '+label+' reference')
            result.append(matches[0]);continue
        classes=[kind for kind in targets if text.startswith(kind+'.')]
        if len(classes)!=1 or (item.tail or '').strip():raise ValueError('Unexpected reference class')
        target=classes[0];prefix=target+'.'
        matches=[oid for oid,d in objects.items() if s.val(d[0][2])==c.identifiers.class_id(target) and s.val(d[0][9])==text[len(prefix):]]
        if len(matches)!=1 or matches[0] in result:raise ValueError('Missing, ambiguous or duplicate metadata reference: '+text)
        result.append(matches[0])
    return result
