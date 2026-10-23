"""Shared strict XML reader driven by verified native object profiles."""
import inline_metadata_xml as inline_metadata
import xdto_type_xml
import metadata_context
import metadata_identifiers
import xml_namespaces
import re
import uuid
from dataclasses import dataclass
import xml.etree.ElementTree as E
import native_metadata as s
import platform_profiles as platforms
import object_xml_profiles as profiles
import type_description_xml as types
import metadata_localized_xml as localized
import metadata_common_xml as common_xml

Q='{'+xml_namespaces.MD+'}'


@dataclass(frozen=True)
class PreparedCreation:
    source: str
    platform: str
    kind: str
    forms: tuple
    templates: tuple
    types: tuple
    xdto: tuple
    result: tuple


def prepare_creation(text,platform,kind,forms,objects,parent,reference_objects,templates,type_references=None,allocation=None,xdto_types=None):
    oid,name,body,generated=create(text,platform,kind,forms,objects,parent,reference_objects,templates,type_references=type_references,allocation=allocation,xdto_types=xdto_types)
    return PreparedCreation(text,platform,kind,tuple(sorted(forms.items())),tuple(sorted(templates.items())),tuple(sorted((type_references or {}).items())),xdto_type_xml.freeze(xdto_types),(oid,name,body,tuple(generated)))


@dataclass(frozen=True)
class TypeAllocation:
    platform: str
    kind: str
    object_id: str
    name: str
    generated: tuple


def generated_ids(obj,layout,kind,name,oid):
    internal=obj.find(Q+'InternalInfo');result=[]
    if internal is not None:
        categories=layout.get('generated_categories',('Object','Ref','Selection','List','Manager'))
        if len(internal)!=len(categories):raise ValueError(f'Expected {len(categories)} generated {kind} types')
        for node,category in zip(internal,categories):
            if node.tag!='{%s}GeneratedType'%xml_namespaces.READABLE or node.attrib!={'name':profiles.generated_name(kind,category,name),'category':category} or [n.tag for n in node]!=['{%s}TypeId'%xml_namespaces.READABLE,'{%s}ValueId'%xml_namespaces.READABLE] or any(n.attrib or len(n) for n in node):raise ValueError(f'Unsupported generated {kind} type')
            result.extend(metadata_context.guid(n.text) for n in node)
    else:result=[str(uuid.uuid4()) for _ in layout['generated_slots']]
    if len(result)!=len(layout['generated_slots']) or len(set(result+[oid]))!=len(result)+1:raise ValueError(f'Duplicate generated {kind} UUID or invalid count')
    return result


def allocate_creation(text,platform,kind):
    if not isinstance(text,str) or len(text.encode('utf-8'))>s.MAX_BYTES or '<!DOCTYPE' in text.upper():raise ValueError('Invalid creation declaration XML')
    top=E.fromstring(text);layout=profiles.layout(kind,platform)
    if top.tag!=Q+'MetaDataObject' or not platforms.xml_attributes(top.attrib,platform) or len(top)!=1 or top[0].tag!=Q+profiles.xml_kind(kind) or set(top[0].attrib)!={'uuid'}:raise ValueError('Unexpected creation declaration class')
    oid=metadata_context.guid(top[0].get('uuid'));name=top[0].findtext(Q+'Properties/'+Q+'Name') or ''
    if not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE):raise ValueError('Invalid creation declaration name')
    return TypeAllocation(platform,kind,oid,name,tuple(generated_ids(top[0],layout,kind,name,oid)))


def object_xml(text, platform, kind,objects=None,*,type_references=None,allocation=None,xdto_types=None):
    if kind not in profiles.profiles():raise ValueError('Unsupported metadata object kind')
    layout=profiles.layout(kind,platform)
    type_property=layout.get('type_property','Type')
    if platforms.profile(platform) not in layout.get('supported_platforms',['legacy']):raise ValueError(kind+' requires legacy platform profile')
    if not isinstance(text,str) or len(text.encode('utf-8'))>s.MAX_BYTES:raise ValueError(f'Oversized {kind} XML')
    if '<!DOCTYPE' in text.upper():raise ValueError('DOCTYPE is unsupported')
    try:top,namespace_scopes=xml_namespaces.parse(text)
    except E.ParseError as error:raise ValueError('Invalid object XML: '+str(error)) from None
    if top.tag!='{%s}MetaDataObject'%xml_namespaces.MD or not platforms.xml_attributes(top.attrib,platform) or len(top)!=1 or top[0].tag!='{%s}%s'%(xml_namespaces.MD,profiles.xml_kind(kind)):
        raise ValueError(f'Expected MetaDataObject/{kind} XML with a legacy XML version')
    obj=top[0]
    if set(obj.attrib)!={'uuid'}:raise ValueError(f'Unsupported {kind} attributes')
    oid=metadata_context.guid(obj.attrib['uuid'])
    permitted={'{%s}%s'%(xml_namespaces.MD,key) for key in layout.get('sections',('Properties','InternalInfo','ChildObjects'))}
    if len({n.tag for n in obj})!=len(obj) or any(n.tag not in permitted or n.attrib for n in obj):raise ValueError(f'Unsupported {kind} section')
    child=obj.find('{%s}ChildObjects'%xml_namespaces.MD)
    if kind != 'Enum' and not layout.get('inline_collections') and not layout.get('tabular_collections') and not layout.get('child_collections') and not layout.get('structured_collections') and child is not None and (len(child) or (child.text or '').strip()):raise ValueError(f'{kind} children are unsupported')
    props=obj.find('{%s}Properties'%xml_namespaces.MD)
    if props is None or len({n.tag for n in props})!=len(props):raise ValueError(f'Missing or duplicate {kind} properties')
    fields={n.tag.removeprefix('{%s}'%xml_namespaces.MD):n for n in props}
    if any(n.tag!='{%s}%s'%(xml_namespaces.MD,key) for key,n in fields.items()):raise ValueError('Unexpected property namespace')
    if 'Name' not in fields:raise ValueError('Missing metadata Name')
    missing=set(layout.get('required_properties',[]))-set(fields)
    if missing:raise ValueError('Missing required metadata properties: '+','.join(sorted(missing)))
    name=fields['Name'].text or ''
    if not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE):raise ValueError(f'Invalid {kind} name')
    for key,node in fields.items():
        if node.attrib and node.attrib!=layout.get('property_attributes',{}).get(key):raise ValueError(f'Unsupported {kind} property attributes: '+key)
        if key in layout.get('field_lists',{}):continue
        if key=='InputByString' and not layout['input_fields']:raise ValueError(f'Unsupported {kind} property: '+key)
        if key in ('Synonym','InputByString'):continue
        if key in layout.get('localized_properties',{}):continue
        if key in layout.get('reference_lists',{}):continue
        if key in layout.get('reference_values',{}):continue
        if key==type_property and 'type_path' in layout:continue
        if key in layout.get('scalar_properties',{}):
            if len(node):raise ValueError('Unsupported '+kind+' property value: '+key)
            try:common_xml.scalar_value(node.text or '',layout['scalar_properties'][key])
            except ValueError as error:raise ValueError('Unsupported '+kind+' property value: '+key+'; '+str(error)) from None
            continue
        if key in layout.get('string_slots',{}):
            if len(node) or (not node.text and key not in layout.get('empty_strings',[])) or '\0' in (node.text or ''):raise ValueError('Invalid '+kind+' property: '+key)
            continue
        if len(node):raise ValueError(f'Unsupported nested {kind} property: '+key)
        if key in ('Name','Comment'):continue
        if key not in layout['defaults'] or (node.text or '')!=layout['defaults'][key]:raise ValueError(f'Unsupported {kind} property: '+key)
    if 'InputByString' in fields and 'InputByString' not in layout.get('field_lists',{}):
        expected=[profiles.xml_kind(kind)+'.'+name+'.StandardAttribute.'+v for v in layout['input_fields']]
        node=fields['InputByString']
        if [n.text for n in node]!=expected or any(n.tag!='{%s}Field'%xml_namespaces.READABLE or n.attrib or len(n) for n in node):raise ValueError('Unsupported InputByString')
    docs=s.Parser(layout['template']).documents();native=docs[0][1]
    if 'common_path' in layout:
        common=docs[0]
        for slot in layout['common_path']:common=common[slot]
    else:
        common=native[layout.get('common_slot',9)]
        if not layout.get('common_direct'):common=common[1]
    common_xml.apply(common,fields,oid)
    if allocation is None:ids=generated_ids(obj,layout,kind,name,oid)
    else:
        if not isinstance(allocation,TypeAllocation) or (allocation.platform,allocation.kind,allocation.object_id,allocation.name)!=(platform,kind,oid,name):raise ValueError('Creation type allocation identity mismatch')
        ids=list(allocation.generated)
        if obj.find(Q+'InternalInfo') is not None and generated_ids(obj,layout,kind,name,oid)!=ids:raise ValueError('Creation generated UUIDs differ from allocation')
    for index,value in zip(layout['generated_slots'],ids):native[index]=s.atom(value)
    for key,profile in layout.get('scalar_properties',{}).items():
        if key not in fields:continue
        node=docs[0]
        for slot in profile['path'][:-1]:node=node[slot]
        node[profile['path'][-1]]=s.atom(common_xml.scalar_value(fields[key].text or '',profile),profile.get('quoted',False))
    for key,path in layout.get('localized_properties',{}).items():
        node=docs[0]
        for slot in path[:-1]:node=node[slot]
        node[path[-1]]=localized.read(fields.get(key),key)
    if layout.get('field_lists'):
        import metadata_field_lists
        rule=layout['field_references']
        for key,field_rule in layout['field_lists'].items():
            index=metadata_field_lists.xml_index(obj,kind,name,rule,field_rule.get('requires_indexing',False),field_rule.get('standard_fields'),field_rule.get('scalar_types'))
            value=metadata_field_lists.read(fields.get(key),index,rule)
            if value is not None:at(docs[0],field_rule['path'][:-1])[field_rule['path'][-1]]=value
            else:
                try:metadata_field_lists.field_names(at(docs[0],field_rule['path']),index,rule)
                except ValueError as error:raise ValueError('Invalid default metadata field list: '+key+'; '+str(error)) from None
    for key,profile in layout.get('reference_values',{}).items():
        field=fields.get(key)
        if field is None or not (field.text or ''):
            if profile.get('required') or ('required_when_nonzero' in profile and s.val(at(docs[0],profile['required_when_nonzero']))!='0'):
                raise ValueError('Required metadata reference: '+key)
            value=s.ZERO
        else:
            if field.attrib or len(field):raise ValueError('Invalid metadata reference: '+key)
            wrapper=E.Element('References');E.SubElement(wrapper,'{'+xml_namespaces.READABLE+'}Item').text=field.text
            value=reference_ids(wrapper,profile,objects or {},oid)[0]
        node=docs[0]
        for slot in profile['path'][:-1]:node=node[slot]
        node[profile['path'][-1]]=s.atom(value)
        if 'member_path' in profile:
            path=profile['member_path'];at(docs[0],path[:-1])[path[-1]]=s.atom(field.text.rsplit('.',1)[1] if value!=s.ZERO else '',True)
    for key,profile in layout.get('reference_lists',{}).items():
        if profile.get('codec')=='mixed_value_list':
            import metadata_value_list_xml
            values,strings=metadata_value_list_xml.read(fields.get(key),profile,objects or {},namespace_scopes)
            path=profile['strings_path'];at(docs[0],path[:-1])[path[-1]]=metadata_value_list_xml.string_row(strings)
        else:values=reference_ids(fields.get(key),profile,objects or {},scopes=namespace_scopes)
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
        node[path[-1]]=s.atom(fields[key].text or '',True)
    if layout.get('type_required') and type_property not in fields:raise ValueError('Expected a scalar Type description')
    if 'type_path' in layout and type_property in fields:
        node=docs[0];path=layout['type_path']
        for slot in path[:-1]:node=node[slot]
        node[path[-1]]=types.read_metadata(fields[type_property],type_references)
        if layout.get('allowed_type_codes') and any(s.val(arm[0]) not in layout['allowed_type_codes'] for arm in node[path[-1]][1:]):
            raise ValueError('Non-string scalar types require the verified legacy profile')
    object_name=name
    if layout.get('inline_collections') or layout.get('tabular_collections') or layout.get('child_collections') or layout.get('command_collections') or layout.get('structured_collections'):
        import inline_object_xml as inline
        names=set();command_names=set();feature_ids=[]
        bindings=namespace_scopes
        for n in ([] if child is None else child):
            key=n.tag.removeprefix('{'+xml_namespaces.MD+'}')
            if n.tag!='{'+xml_namespaces.MD+'}'+key:raise ValueError('Unsupported inline namespace')
            if kind=='Enum' and key=='EnumValue':continue  # Values have their own native template below.
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
                profile=layout['command_collections'][key];aid,aname,entry=inline_metadata.read(n,profile,type_references=type_references);new_features=[aid];name_scope=command_names
            elif key in layout.get('structured_collections',{}):
                profile=layout['structured_collections'][key];aid,aname,entry=inline_metadata.read(n,profile,type_references=type_references,bindings=bindings,xdto_types=xdto_types);new_features=[oid for oid,_ in inline_metadata.identities(entry,profile)]
            elif key in layout.get('tabular_collections',{}):
                import tabular_section_xml as tabular
                profile=layout['tabular_collections'][key];aid,aname,entry,new_features,generated=tabular.read(n,object_name,kind=profile['kind'],type_references=type_references)
            elif key in layout.get('inline_collections',{}):
                profile=layout['inline_collections'][key];aid,aname,entry=inline.read(n,profile,type_references=type_references);new_features=[aid]
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
                if value.tag==Q+'Command' and layout.get('command_collections'):continue
                if value.tag!='{%s}EnumValue'%xml_namespaces.MD or set(value.attrib)!={'uuid'} or len(value)!=1 or value[0].tag!='{%s}Properties'%xml_namespaces.MD:
                    raise ValueError('Only inline EnumValue properties are supported')
                vid=metadata_context.guid(value.get('uuid'));props=value[0]
                if props.attrib or len({p.tag for p in props})!=len(props):raise ValueError('Invalid EnumValue properties')
                fields={p.tag.removeprefix('{%s}'%xml_namespaces.MD):p for p in props}
                if any(p.tag!='{%s}%s'%(xml_namespaces.MD,k) or p.attrib for k,p in fields.items()):raise ValueError('Invalid EnumValue property')
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


def reference_ids(node,profile,objects,owner=None,*,scopes=None):
    import metadata_targets
    references=metadata_targets.index(objects)
    targets=profile['target'] if isinstance(profile['target'],list) else [profile['target']]
    if node is None or not len(node):
        if profile.get('required'):raise ValueError('Required reference list: '+','.join(targets))
        return []
    if node.attrib or (node.text or '').strip():raise ValueError('Invalid reference list')
    result=[]
    for item in node:
        type_key='{http://www.w3.org/2001/XMLSchema-instance}type'
        if item.tag!='{'+xml_namespaces.READABLE+'}Item' or len(item) or set(item.attrib)-{type_key}:raise ValueError('Unsupported metadata reference')
        if type_key in item.attrib:
            from typed_value_xml import qname
            if scopes is None:
                if item.get(type_key)!='xr:MDObjectRef':raise ValueError('Unsupported metadata reference type')
            elif qname(item.get(type_key),xml_namespaces.context(scopes,item))!=(xml_namespaces.READABLE,'MDObjectRef'):raise ValueError('Unsupported metadata reference type')
        text=item.text or ''
        if 'member_path' in profile:
            parts=text.rsplit('.',1)
            if len(parts)!=2 or not re.fullmatch(r'[^\W\d]\w{0,79}',parts[1],re.UNICODE):raise ValueError('Invalid metadata method reference')
            text=parts[0]
        if profile.get('owner_kind'):
            if profile.get('owned_tag','Form')=='Form' and owner is not None:
                value=references.owned_form(text,owner,profile['owner_kind'])
                if value in result:raise ValueError('Duplicate owned form reference')
                result.append(value);continue
            parts=text.split('.')
            child_tag=profile.get('owned_tag','Form');label='form' if child_tag=='Form' else 'child'
            if len(parts)!=4 or parts[0]!=profile['owner_kind'] or parts[2]!=child_tag or not parts[1] or not parts[3] or (item.tail or '').strip():raise ValueError('Invalid owned '+label+' reference')
            owners=[row for row in references.find({metadata_identifiers.class_id(parts[0])},parts[1]) if owner is None or row.object_id==owner]
            if len(owners)!=1:raise ValueError('Missing, ambiguous or foreign '+label+' owner')
            parent=owners[0]
            matches=[row for row in references.find({metadata_identifiers.class_id(kind) for kind in targets},parts[3],parent.object_id) if row.owner_id==s.ZERO]
            if len(matches)!=1 or matches[0].object_id in result or parent.children is None or (matches[0].object_id,matches[0].class_id) not in parent.children:raise ValueError('Missing, ambiguous or unregistered owned '+label+' reference')
            result.append(matches[0].object_id);continue
        classes=[kind for kind in targets if text.startswith(profiles.xml_kind(kind)+'.')]
        if len(classes)!=1 or (item.tail or '').strip():raise ValueError('Unexpected reference class')
        target=classes[0];prefix=profiles.xml_kind(target)+'.'
        matches=references.find({metadata_identifiers.class_id(target)},text[len(prefix):])
        if len(matches)!=1 or matches[0].object_id in result:raise ValueError('Missing, ambiguous or duplicate metadata reference: '+text)
        result.append(matches[0].object_id)
    return result


def at(node,path):
    for slot in path:node=node[slot]
    return node


def common_path(layout):
    return layout.get('common_path',[1,layout.get('common_slot',9)]+([] if layout.get('common_direct') else [1]))


def reference_dependencies(source,layout,oid):
    """Mapped reference values and lists share one native dependency policy."""
    result={}
    for category in ('reference_values','reference_lists'):
        for rule in layout.get(category,{}).values():
            flag=rule.get('relation_flag',0)
            if flag is None:continue
            row=at(source,rule['path'])
            values=([s.val(at(item,rule['id_path'])) for item in row[2:]] if category=='reference_lists' else [s.val(row)])
            for key in values:
                if key!=s.ZERO and not (rule.get('exclude_self_dependency') and key==oid):result[key]=flag
    return result


def create(text,platform,kind,forms=None,objects=None,parent=s.ZERO,reference_objects=None,templates=None,*,type_references=None,allocation=None,xdto_types=None):
    """Create an object and bind its stored children using the same XML profiles."""
    import metadata_targets
    import managed_form_profiles as form_profiles
    import native_collection_editor as collections
    forms={} if forms is None else forms
    templates={} if templates is None else templates
    objects={} if objects is None else objects
    if kind not in form_profiles.owner_profiles():
        if forms or templates:raise ValueError('Metadata class cannot own stored children: '+kind)
        return object_xml(text,platform,kind,reference_objects if reference_objects is not None else objects,type_references=type_references,allocation=allocation,xdto_types=xdto_types)
    if not isinstance(text,str) or len(text.encode('utf-8'))>s.MAX_BYTES or '<!DOCTYPE' in text.upper():raise ValueError('Invalid or oversized object XML')
    root=E.fromstring(text)
    if root.tag!=Q+'MetaDataObject' or len(root)!=1 or root[0].tag!=Q+profiles.xml_kind(kind):raise ValueError('Unexpected object XML class')
    obj=root[0];oid=metadata_context.guid(obj.get('uuid'));name=obj.findtext(Q+'Properties/'+Q+'Name')
    references=reference_objects if reference_objects is not None else metadata_targets.creation(kind,oid,name,forms,objects,parent,templates)
    supplied={'Form':forms,'Template':templates};children=obj.find(Q+'ChildObjects');names={tag:[] for tag in supplied};rules={row['xml_name']:row for row in collections.rules(kind)}
    for node in ([] if children is None else children):
        tag=node.tag.removeprefix(Q)
        if node.tag!=Q+tag or tag not in rules:continue
        if tag not in supplied:raise ValueError('Creating other stored children requires their own converter: '+tag)
        if node.attrib or len(node) or node.text not in supplied[tag] or node.text in names[tag]:raise ValueError('Unknown or duplicate creation '+tag+' reference')
        names[tag].append(node.text)
    for tag in supplied:
        if set(names[tag])!=set(supplied[tag]):raise ValueError(tag+' files do not match '+kind+' references')
    stripped=collections.strip_xml(text,kind)
    oid,name,raw,generated=object_xml(stripped,platform,kind,references,type_references=type_references,allocation=allocation,xdto_types=xdto_types)
    body=s.Parser(raw.decode('utf-8-sig')).documents()[0]
    for tag,ordered in names.items():
        if tag not in rules:
            if ordered:raise ValueError('Metadata class cannot own '+tag+': '+kind)
            continue
        row=collections.creation_row(body,rules[tag]['item_class_id'])
        if len(row)!=2:raise ValueError('New owner must start with an empty '+tag+' collection')
        row[:]=[row[0],s.atom(len(ordered))]+[s.atom(supplied[tag][name]) for name in ordered]
    return oid,name,s.native_body_bytes([body]),generated


def change(text,platform,kind,source,forms=None,removed=(),*,objects=None,metadata=None,reference_objects=None,type_references=None,xdto_types=None,allow_rename=False):
    """Rebuild a full object while preserving opaque fields and generated IDs.

    Name changes need explicit orchestration: the caller must also reconcile the
    descriptor, owner and final reference index. The complete-export compiler
    opts in after matching UUIDs; individual packet paths keep this disabled.
    """
    allowed=profiles.profiles().get(kind,{}).get('change_platforms')
    if allowed is not None and platforms.profile(platform) not in allowed:raise ValueError('Object changes require a verified platform profile: '+kind)
    import copy
    import inline_object_xml as inline
    import metadata_targets
    import native_collection_editor as collections
    import metadata_structure
    import child_object_xml
    import tabular_section_xml as tabular
    layout=profiles.layout(kind,platform);path=common_path(layout);common=at(source,path)
    oid=metadata_context.guid(s.val(common[1][2]));name=s.val(common[2])
    objects={} if objects is None else objects
    references=reference_objects if reference_objects is not None else objects
    if forms is not None and reference_objects is None:
        references=metadata_targets.creation(kind,oid,name,forms,objects)
    editing=metadata is not None and kind in metadata_structure.automatic_owners() and bool(collections.rules(kind))
    converted=collections.strip_xml(text,kind) if editing else text
    actual,target_name,raw,_=object_xml(converted,platform,kind,references,type_references=type_references,xdto_types=xdto_types)
    if actual!=oid:raise ValueError('Object XML UUID differs from repository')
    if target_name!=name and not allow_rename:raise ValueError('Object XML identity differs from repository; rename is unsupported')
    target=s.Parser(raw.decode('utf-8-sig')).documents()[0]
    if editing:
        target=collections.restore(target,source,kind,metadata,objects)
        target=collections.edit(target,kind,metadata,objects,removed)
    elif metadata is not None:
        child_object_xml.validate(source,target,layout,metadata,objects,removed=removed)
    else:
        for rule in layout.get('child_collections',{}).values():
            old=source[rule['slot']];new=target[rule['slot']]
            if [s.val(v) for v in old[2:] if s.val(v) not in removed]!=[s.val(v) for v in new[2:]]:
                raise ValueError('Existing child references and order must be preserved')
    for rule in layout.get('tabular_collections',{}).values():
        previous={s.val(tabular.common(entry)[1][2]):entry for entry in source[rule['slot']][2:]}
        for entry in target[rule['slot']][2:]:
            old=previous.get(s.val(tabular.common(entry)[1][2]))
            if old is not None and s.render(entry[0][1][1:5])!=s.render(old[0][1][1:5]):
                raise ValueError('Existing TabularSection generated UUIDs must remain unchanged')
    if E.fromstring(text)[0].find(Q+'InternalInfo') is None:
        for slot in layout['generated_slots']:target[1][slot]=copy.deepcopy(source[1][slot])
    baseline=copy.deepcopy(target)
    mutable=[path+[3],path+[4]]+list(layout.get('string_slots',{}).values())
    if allow_rename:mutable.append(path+[2])
    mutable.extend(rule['path'] for rule in layout.get('scalar_properties',{}).values())
    mutable.extend(layout.get('localized_properties',{}).values())
    mutable.extend(rule['path'] for rule in layout.get('field_lists',{}).values())
    if 'type_path' in layout:mutable.append(layout['type_path'])
    for category in ('reference_lists','reference_values'):
        mutable.extend(rule['path'] for rule in layout.get(category,{}).values())
    mutable.extend(rule['member_path'] for rule in layout.get('reference_values',{}).values() if 'member_path' in rule)
    mutable.extend(rule['strings_path'] for rule in layout.get('reference_lists',{}).values() if rule.get('codec')=='mixed_value_list')
    for category in ('inline_collections','tabular_collections','command_collections','structured_collections'):
        mutable.extend([rule['slot']] for rule in layout.get(category,{}).values())
    mutable.extend([rule['slot']] for rule in layout.get('child_collections',{}).values())
    if editing:mutable.extend(row['path'] for row in collections.inspect(source,kind,metadata,objects))
    if 'values_slot' in layout:mutable.append([layout['values_slot']])
    for field in mutable:at(baseline,field[:-1])[field[-1]]=copy.deepcopy(at(source,field))
    if s.render(baseline)!=s.render(source):raise ValueError('Source body or generated identifiers are outside the verified whole-object profile')
    old_features=inline.features(source,layout);features=inline.features(target,layout)
    old_scopes,new_scopes=inline.scopes(source,layout),inline.scopes(target,layout)
    if any(old_scopes[key]!=new_scopes[key] for key in old_scopes.keys()&new_scopes.keys()):raise ValueError('Existing inline UUID cannot move between collections')
    return s.native_body_bytes([target]),features


def export(source,forms,platform,kind,*,objects=None,type_references=None,xdto_types=None):
    """Export supported properties and collections from a verified native body."""
    import copy
    import inline_attribute_xml as attributes
    import tabular_section_xml as tabular
    import metadata_targets
    layout=profiles.layout(kind,platform);common=at(source,common_path(layout));name=s.val(common[2]);oid=s.val(common[1][2])
    top=E.Element(Q+'MetaDataObject',version='2.21' if platforms.legacy(platform) else '2.22')
    for prefix,uri in xdto_type_xml.bindings(xdto_types).items():top.set('xmlns:'+prefix,uri)
    obj=E.SubElement(top,Q+profiles.xml_kind(kind),uuid=oid)
    slots=layout['generated_slots']
    if slots:
        internal=E.SubElement(obj,Q+'InternalInfo')
        for index,category in enumerate(layout.get('generated_categories',('Object','Ref','Selection','List','Manager'))):
            typ=E.SubElement(internal,'{'+xml_namespaces.READABLE+'}GeneratedType',name=profiles.generated_name(kind,category,name),category=category)
            for field,slot in zip(('TypeId','ValueId'),slots[index*2:index*2+2]):E.SubElement(typ,'{'+xml_namespaces.READABLE+'}'+field).text=s.val(source[1][slot])
    props=E.SubElement(obj,Q+'Properties');common_xml.write(props,common)
    fields={key:E.SubElement(props,Q+key) for key in layout['defaults']}
    for key,value in layout['defaults'].items():fields[key].text=value
    def field(key):
        if key not in fields:fields[key]=E.SubElement(props,Q+key)
        return fields[key]
    for key,rule in layout.get('scalar_properties',{}).items():
        field(key).text=common_xml.scalar_text(at(source,rule['path']),rule)
    for key,path in layout.get('string_slots',{}).items():field(key).text=s.val(at(source,path))
    for key,path in layout.get('localized_properties',{}).items():localized.write(field(key),at(source,path),key)
    if 'type_path' in layout:props.append(types.export_metadata(at(source,layout['type_path']),Q+layout.get('type_property','Type'),type_references))
    references=metadata_targets.index(objects or {})
    reverse={value:key for key,value in forms.items()}
    for key,rule in layout.get('reference_lists',{}).items():
        row=at(source,rule['path'])
        if not isinstance(row,list) or len(row)<2 or s.val(row[0])!='0' or int(s.val(row[1]))!=len(row)-2:raise ValueError('Unsupported native reference list: '+key)
        node=field(key)
        if rule.get('codec')=='mixed_value_list':
            import metadata_value_list_xml
            metadata_value_list_xml.export(node,row,at(source,rule['strings_path']),rule,references)
            continue
        for entry in row[2:]:
            oid_value=s.val(at(entry,rule['id_path']));attrs={}
            if rule.get('xml_type'):
                node.set('xmlns:mdref',xml_namespaces.READABLE);attrs['{http://www.w3.org/2001/XMLSchema-instance}type']='mdref:'+rule['xml_type']
            E.SubElement(node,'{'+xml_namespaces.READABLE+'}Item',attrs).text=references.qualified(oid_value)
    for key,rule in layout.get('reference_values',{}).items():
        value=s.val(at(source,rule['path']))
        if value==s.ZERO:continue
        if rule.get('owner_kind') and value in reverse:field(key).text=profiles.xml_kind(kind)+'.'+name+'.Form.'+reverse[value]
        else:
            matches=[row for row in references.targets if row.object_id==value]
            if len(matches)!=1:raise ValueError('Unknown native metadata reference: '+key)
            field(key).text=profiles.xml_kind(metadata_identifiers.class_labels()[matches[0].class_id])+'.'+matches[0].name
        if 'member_path' in rule:
            member=s.val(at(source,rule['member_path']))
            if not re.fullmatch(r'[^\W\d]\w{0,79}',member,re.UNICODE):raise ValueError('Invalid native metadata method name')
            field(key).text+='.'+member
    if layout.get('field_lists'):
        import metadata_field_lists
        rule=layout['field_references']
        for key,field_rule in layout['field_lists'].items():
            index=metadata_field_lists.native_index(source,kind,name,rule,field_rule.get('requires_indexing',False),field_rule.get('standard_fields'),field_rule.get('scalar_types'))
            metadata_field_lists.export(field(key),at(source,field_rule['path']),index,rule)
    if layout['input_fields'] and 'InputByString' not in layout.get('field_lists',{}):
        input_by=E.SubElement(props,Q+'InputByString')
        for key in layout['input_fields']:E.SubElement(input_by,'{'+xml_namespaces.READABLE+'}Field').text=profiles.xml_kind(kind)+'.'+name+'.StandardAttribute.'+key
    import native_collection_editor as collections
    templates={}
    stored=[rule for rule in collections.rules(kind) if rule['native']['status'] in ('verified_profile','snapshot_collection')]
    if layout.get('inline_collections') or layout.get('tabular_collections') or stored or layout.get('command_collections') or layout.get('structured_collections') or 'values_slot' in layout:
        children=E.SubElement(obj,Q+'ChildObjects')
        if 'values_slot' in layout:
            default=s.Parser(layout['value_template']).documents()[0]
            for entry in source[layout['values_slot']][2:]:
                if s.render(at(entry,layout['value_color_path']))!=s.render(at(default,layout['value_color_path'])):raise ValueError('EnumValue color XML export is outside the verified profile')
                common_value=entry[0][1];node=E.SubElement(children,Q+'EnumValue',uuid=s.val(common_value[1][2]));common_xml.write(E.SubElement(node,Q+'Properties'),common_value)
        for tag,rule in layout.get('inline_collections',{}).items():
            xml_name=rule.get('xml_name','Attribute')
            if tag!=xml_name and len(source[rule['slot']])>2:raise ValueError('XML export is not implemented for inline '+tag)
            for entry in source[rule['slot']][2:]:children.append(attributes.attribute_export(entry,rule['template'],type_references=type_references,filling=rule.get('filling',True),property_names=rule.get('properties'),xml_name=xml_name))
        for rule in layout.get('tabular_collections',{}).values():
            for entry in source[rule['slot']][2:]:children.append(tabular.export(entry,name,rule['kind'],type_references=type_references))
        if layout.get('command_collections'):
            for rule in layout['command_collections'].values():
                for entry in source[rule['slot']][2:]:children.append(inline_metadata.export(entry,rule,type_references=type_references))
        for rule in layout.get('structured_collections',{}).values():
            for entry in inline_metadata.entries(source,rule):children.append(inline_metadata.export(entry,rule,type_references=type_references,xdto_types=xdto_types))
        for rule in stored:
            tag=rule['xml_name'];row=collections.creation_row(source,rule['item_class_id'])
            for value in row[2:]:
                key=s.val(value)
                if tag=='Form' and key in reverse:child_name=reverse[key]
                else:
                    matches=[row for row in references.targets if row.class_id==rule['item_class_id'] and row.parent_id==oid]
                    matches=[row for row in matches if row.object_id==key]
                    if len(matches)!=1:raise ValueError('Unknown native child reference: '+tag)
                    child_name=matches[0].name
                E.SubElement(children,Q+tag).text=child_name
                if tag=='Template':templates[child_name]=key
    # Export must never silently omit a native field or collection that is not
    # represented by the current XML writer.
    references=metadata_targets.index(objects or {})
    if (forms or templates) and not any(row.object_id==oid for row in references.targets):references=metadata_targets.creation(kind,oid,name,forms,references,templates=templates)
    _,_,rebuilt,_=create(xml_namespaces.serialize(top),platform,kind,forms,objects=references,reference_objects=references,templates=templates,type_references=type_references,xdto_types=xdto_types)
    comparison=copy.deepcopy(source)
    for rule in layout.get('inline_collections',{}).values():
        group=comparison[rule['slot']]
        group[2:]=[attributes.canonical_filling(entry,filling=rule.get('filling',True)) for entry in group[2:]]
    if s.render(s.Parser(rebuilt.decode('utf-8-sig')).documents()[0])!=s.render(comparison):
        raise ValueError('Native object contains fields outside the supported XML export profile')
    return top
