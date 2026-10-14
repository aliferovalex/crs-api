"""Recursive control tree, commands and event bindings for the verified profile."""
import copy,json,re
from pathlib import Path
from xml.etree import ElementTree as E
import metadata_serializer as s

Q='{http://v8.1c.ru/8.3/xcf/logform}'
CORE='{http://v8.1c.ru/8.1/data/core}'


def layouts():
    data=json.loads(Path(__file__).with_name('managed_form_elements_851.json').read_text(encoding='utf-8'))
    field=json.loads(Path(__file__).with_name('managed_form_field_layout_851.json').read_text(encoding='utf-8'))
    data['elements']['InputField']=dict(type=field['element_type'],version='48',name_slot=6,title_slot=9,enabled_slot=13,visible_slot=43,template=field['template'],discriminator={'slot':5,'value':'2'})
    data['elements']['Table']=json.loads(Path(__file__).with_name('managed_form_table_layout_851.json').read_text(encoding='utf-8'))
    data['elements'].update(json.loads(Path(__file__).with_name('managed_form_pages_layout_851.json').read_text(encoding='utf-8'))['elements'])
    data['elements'].update(json.loads(Path(__file__).with_name('managed_form_picture_layout_851.json').read_text(encoding='utf-8'))['elements'])
    data['elements'].update(json.loads(Path(__file__).with_name('managed_form_bound_fields_851.json').read_text(encoding='utf-8'))['elements'])
    return data


GROUPS={'UsualGroup','Pages','Page'}
DATA_FIELDS={'InputField','CheckBoxField','LabelField'}
BOUND_FIELDS=DATA_FIELDS|{'RadioButtonField','ProgressBarField','CalendarField'}
FIELD_TYPE='77ffcc29-7f2d-4223-b22f-19666e7250ba'


def field_header_size(entry):
    """Field's optional native property block precedes its subtype and name."""
    if len(entry)<6 or not isinstance(entry[3],s.Atom) or s.val(entry[3])!='0':raise ValueError('Unsupported field header')
    if not isinstance(entry[4],s.Atom) or not re.fullmatch(r'0|[1-9][0-9]{0,2}',s.val(entry[4])):raise ValueError('Invalid field property count')
    count=int(s.val(entry[4]))
    if 5+count>=len(entry):raise ValueError('Truncated field property header')
    return count


def field_layout_version(entry):
    version=s.val(entry[0]);size={'47':72,'48':74}.get(version)
    if size is None or len(entry)-field_header_size(entry)!=size:raise ValueError('Unsupported field layout version or size')
    return version


def upgrade_field(entry):
    """Promote the verified v47 layout in place; existing slots stay unchanged."""
    if field_layout_version(entry)=='47':
        entry[0]=s.atom(48);entry.extend([s.atom(0),s.atom(0)])


def native_kind(type_id,entry,data):
    if not isinstance(entry,list) or not entry or not isinstance(entry[0],s.Atom):raise ValueError('Invalid native control')
    version=field_layout_version(entry) if type_id==FIELD_TYPE else s.val(entry[0])
    if type_id==FIELD_TYPE and version=='47':version='48'
    matches=[]
    for kind,profile in data['elements'].items():
        if profile['type']!=type_id or profile['version']!=version:continue
        discriminator=profile.get('discriminator')
        if discriminator:
            slot=discriminator['slot']
            if type_id==FIELD_TYPE:slot+=field_header_size(entry)
            if slot>=len(entry) or not isinstance(entry[slot],s.Atom) or s.val(entry[slot])!=discriminator['value']:continue
        matches.append((kind,profile))
    if len(matches)!=1:raise ValueError('Unsupported or ambiguous native control type')
    return matches[0]


def group_children(entry):
    from v8unpack_backend import group_offsets
    return group_offsets(entry)['children']


def table_children(entry):
    from v8unpack_backend import table_offsets
    return table_offsets(entry)['children']


def rename_auxiliary(entry,previous,name):
    for value in entry:
        if not isinstance(value,list):continue
        if len(value)>6 and isinstance(value[0],s.Atom) and s.val(value[0]) in ('6','12','22') and isinstance(value[6],s.Atom) and s.val(value[6]).startswith(previous):
            value[6]=s.atom(name+s.val(value[6])[len(previous):],True)
        rename_auxiliary(value,previous,name)


def table_addition(xml,entry,kind,table_name):
    """Accept native-exported default search/view additions without losing edits."""
    names={'SearchStringAddition':('СтрокаПоиска','SearchStringRepresentation'),
           'ViewStatusAddition':('СостояниеПросмотра','ViewStatusRepresentation'),
           'SearchControlAddition':('УправлениеПоиском','SearchControl')}
    suffix,source_type=names[kind]
    if set(xml.attrib)!={'name','id'} or not re.fullmatch('[1-9][0-9]{0,8}',xml.get('id','')):raise ValueError('Invalid table addition')
    props=fields(xml,{'AdditionSource','ContextMenu','ExtendedTooltip'});source=props.get('AdditionSource')
    if source is None or source.attrib:raise ValueError('Missing table addition source')
    parts=fields(source,{'Item','Type'})
    if set(parts)!={'Item','Type'} or scalar(parts['Item'])!=table_name or scalar(parts['Type'])!=source_type:raise ValueError('Unsupported table addition source')
    candidates=[v for v in entry if isinstance(v,list) and len(v)>6 and isinstance(v[0],s.Atom) and s.val(v[0])=='6' and s.val(v[6])==table_name+suffix]
    if len(candidates)!=1:raise ValueError('Unsupported native table addition')
    target=candidates[0];previous=s.val(target[6]);name=identifier(xml.get('name'));target[6]=s.atom(name,True);rename_auxiliary(target,previous,name)
    for key,version in [('ContextMenu','22'),('ExtendedTooltip','12')]:
        if key in props:auxiliary(props[key],target,version)


def auxiliary(xml,entry,version,bar_type='8'):
    if len(xml) or set(xml.attrib)!={'name','id'} or not re.fullmatch('[1-9][0-9]{0,8}',xml.get('id','')):raise ValueError('Unsupported auxiliary control')
    matches=[v for v in entry if isinstance(v,list) and len(v)>6 and isinstance(v[0],s.Atom) and s.val(v[0])==version and isinstance(v[6],s.Atom)
        and isinstance(v[1],list) and len(v[1])==1 and isinstance(v[1][0],s.Atom) and s.val(v[1][0])=='0' and (version!='22' or s.val(v[5])==bar_type)]
    if len(matches)!=1:raise ValueError('Unsupported auxiliary native layout')
    matches[0][6]=s.atom(identifier(xml.get('name')),True)


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[^\W\d]\w{0,79}',value,re.UNICODE):raise ValueError('Invalid form element or handler name')
    return value


def fields(node,allowed):
    result={}
    for child in node:
        key=child.tag.removeprefix(Q)
        if child.tag!=Q+key or key not in allowed or key in result:raise ValueError('Unsupported or duplicate '+node.tag+' property: '+child.tag)
        result[key]=child
    return result


def scalar(node,default=None):
    if node is None:return default
    if node.attrib or len(node):raise ValueError('Expected scalar form property')
    return node.text or ''


def boolean(node,default):
    value=scalar(node,'true' if default else 'false')
    if value not in ('true','false'):raise ValueError('Expected boolean form property')
    return s.atom(1 if value=='true' else 0)


def title(node,plain_decoration=False):
    result=[s.atom(1),s.atom(0)];languages=set()
    if node is None:return result
    if node.attrib and not (plain_decoration and node.attrib=={'formatted':'false'}):raise ValueError('Unsupported Title attributes')
    for item in node:
        if item.tag!=CORE+'item' or item.attrib or len(item)!=2 or [n.tag for n in item]!=[CORE+'lang',CORE+'content'] or any(n.attrib or len(n) for n in item):raise ValueError('Unsupported localized Title')
        lang=item[0].text or ''
        if not lang or lang in languages:raise ValueError('Missing or duplicate Title language')
        languages.add(lang);result.append([s.atom(lang,True),s.atom(item[1].text or '',True)])
    result[1]=s.atom(len(languages));return result


def events(node,kind,previous,allowed=None):
    from managed_form_rules import event_names
    if allowed is None:allowed=event_names(kind)
    if not isinstance(previous,list) or not previous or any(not isinstance(v,s.Atom) for v in previous) or previous[0].quoted:raise ValueError('Invalid native events')
    try:count=int(s.val(previous[0]))
    except (ValueError,TypeError):raise ValueError('Invalid native event count') from None
    if count<0 or len(previous)!=3+5*count:raise ValueError('Unsupported native event layout')
    if [s.val(v) for v in previous[1+2*count:3+2*count]]!=['1','0']:raise ValueError('Unsupported native event flags')
    guids=set()
    for j in range(count):
        i=1+2*j;guid=s.val(previous[i])
        if guid not in allowed.values() or guid in guids or not previous[i+1].quoted or [s.val(v) for v in previous[3+2*count+3*j:6+2*count+3*j]]!=[guid,'0','1']:raise ValueError('Unsupported native event binding')
        guids.add(guid)
    selected={}
    if node is not None:
        if node.attrib:raise ValueError('Unsupported Events attributes')
        for event in node:
            name=event.get('name')
            if event.tag!=Q+'Event' or event.attrib!={'name':name} or len(event) or name not in allowed or name in selected:raise ValueError('Unsupported or duplicate form event')
            selected[name]=identifier(event.text or '')
    ordered=sorted((allowed[name],handler) for name,handler in selected.items())
    result=[s.atom(len(ordered))]
    for guid,handler in ordered:result.extend([s.atom(guid),s.atom(handler,True)])
    result.extend([s.atom(1),s.atom(0)])
    for guid,_ in ordered:result.extend([s.atom(guid),s.atom(0),s.atom(1)])
    return result


def collection(node,index):
    data=layouts()
    if index>=len(node) or isinstance(node[index],list):raise ValueError('Invalid native control count')
    count=int(s.val(node[index]));end=index+1+count*2
    if count<0 or count>256 or end>len(node):raise ValueError('Invalid native control collection')
    for i in range(index+1,end,2):
        kind=s.val(node[i]);entry=node[i+1]
        native_kind(kind,entry,data)
    return index,count,end


def form_collection(form):
    props=form[1];bars=[i for i,v in enumerate(props) if isinstance(v,list) and len(v)>6 and isinstance(v[0],s.Atom) and s.val(v[0])=='22' and s.val(v[5])=='9' and s.val(v[6])=='FormCommandBar']
    if len(bars)!=1:raise ValueError('Unsupported or ambiguous control collection')
    return collection(props,bars[0]+1)


def commands(node,previous):
    if not isinstance(previous,list) or len(previous)<2 or [s.val(v) for v in previous[:1]]!=['0'] or int(s.val(previous[1]))!=len(previous)-2:raise ValueError('Unsupported native commands')
    existing={};result=[s.atom(0),s.atom(0)];names={};numbers=set()
    for cmd in previous[2:]:
        if not isinstance(cmd,list) or len(cmd)!=21 or s.val(cmd[0])!='11':raise ValueError('Unsupported native command layout')
        number=int(s.val(cmd[1][0]))
        if number in existing:raise ValueError('Duplicate native command id')
        existing[number]=cmd
    if node is not None:
        if node.attrib:raise ValueError('Unsupported Commands attributes')
        for xml in node:
            name=identifier(xml.get('name'));number=xml.get('id','')
            if xml.tag!=Q+'Command' or set(xml.attrib)!={'name','id'} or not re.fullmatch('[1-9][0-9]{0,8}',number) or int(number) in numbers or name.casefold() in {n.casefold() for n in names}:raise ValueError('Invalid or duplicate command')
            numbers.add(int(number));props=fields(xml,{'Action','Title'})
            action=identifier(scalar(props.get('Action'),''));entry=copy.deepcopy(existing.get(int(number)))
            if entry is None:entry=s.Parser(layouts()['command_template']).documents()[0]
            entry[1][0]=s.atom(number);entry[2]=s.atom(name,True);entry[3]=title(props.get('Title'));entry[8]=s.atom(action,True)
            names[name]=(int(number),s.val(entry[1][1]));result.append(entry)
    result[1]=s.atom(len(names));return result,names


def replace_tree(form,items,paths,command_ids,namespaces=None):
    data=layouts();existing={}
    def collect(node,index,depth=0):
        if depth>32:raise ValueError('Form tree is too deep')
        _,_,end=collection(node,index)
        for i in range(index+1,end,2):
            entry=node[i+1];kind,layout=native_kind(s.val(node[i]),entry,data);number=int(s.val(entry[1][0]))
            if number in existing:raise ValueError('Duplicate native control id')
            existing[number]=(kind,entry)
            if kind in GROUPS:collect(entry,group_children(entry),depth+1)
            elif kind=='Table':collect(entry,table_children(entry),depth+1)
    index,_,end=form_collection(form);collect(form[1],index)
    numbers=set();names=set()
    def build(nodes,depth=0,table_path=None,parent_kind=None):
        if depth>32 or nodes.attrib:raise ValueError('Invalid or too deep ChildItems')
        output=[]
        for xml in nodes:
            kind=xml.tag.removeprefix(Q);name=identifier(xml.get('name'));number=xml.get('id','')
            if xml.tag!=Q+kind or kind not in data['elements'] or set(xml.attrib)!={'name','id'} or not re.fullmatch('[1-9][0-9]{0,8}',number):raise ValueError('Unsupported XML control')
            if table_path is not None and kind not in DATA_FIELDS:raise ValueError('Only data fields are supported as table columns')
            if parent_kind=='Pages' and kind!='Page':raise ValueError('Pages may contain only Page elements')
            if kind=='Page' and parent_kind!='Pages':raise ValueError('Page must belong to Pages')
            number=int(number)
            if number in numbers or name.casefold() in names or len(numbers)>=256:raise ValueError('Duplicate or excessive XML control name or id')
            numbers.add(number);names.add(name.casefold());layout=data['elements'][kind]
            known=existing.get(number)
            if known and known[0]!=kind:raise ValueError('Control type cannot change while preserving its id')
            entry=copy.deepcopy(known[1]) if known else s.Parser(layout['template']).documents()[0]
            # Rules describe the canonical layout. Preserve optional native
            # properties while applying those rules to stable field offsets.
            field_header=[]
            if kind in BOUND_FIELDS:
                upgrade_field(entry)
                count=field_header_size(entry);field_header=entry[5:5+count]
                del entry[5:5+count];entry[4]=s.atom(0)
            name_slot=layout['name_slot'];previous=s.val(entry[name_slot]);entry[name_slot]=s.atom(name,True);entry[1][0]=s.atom(number)
            rename_auxiliary(entry,previous,name)
            common={'Title','Visible','Enabled','ExtendedTooltip'}
            specifics={'UsualGroup':{'Group','ChildItems'},'Button':{'Type','CommandName'},
                'Pages':{'ChildItems'},'Page':{'ChildItems'},'LabelDecoration':{'ContextMenu'},
                'PictureDecoration':{'ContextMenu','Picture'}|set(layout.get('properties',{})),
                'Table':{'DataPath','ChildItems','RowFilter','ContextMenu','AutoCommandBar','SearchStringAddition','ViewStatusAddition','SearchControlAddition'}}
            specifics.update({k:{'DataPath','ContextMenu'} for k in BOUND_FIELDS})
            specifics=specifics[kind]
            import managed_form_rules as rules
            profile=rules.profiles()[kind]
            props=fields(xml,common|specifics|set(profile['properties'])|({'Events'} if profile.get('events') else set()))
            if kind not in ('LabelDecoration','PictureDecoration'):entry[layout['title_slot']]=title(props.get('Title'))
            if kind in BOUND_FIELDS:
                path=scalar(props.get('DataPath'))
                if path not in paths:raise ValueError('Unknown InputField DataPath')
                if kind=='CheckBoxField' and getattr(paths,'types',{}).get(path)!='B':raise ValueError('CheckBoxField requires a boolean DataPath')
                expected=layout.get('binding_type')
                if expected and getattr(paths,'types',{}).get(path)!=expected:raise ValueError(kind+' requires a '+expected+' DataPath')
                if path in getattr(paths,'tables',set()):raise ValueError('InputField cannot bind to a tabular collection')
                if table_path is not None and not path.startswith(table_path+'.'):raise ValueError('Column DataPath belongs to another table')
                if table_path is None and any(path.startswith(t+'.') for t in getattr(paths,'tables',set())):raise ValueError('Tabular attribute requires a table column')
                from v8unpack_backend import field_offsets
                entry[field_offsets(entry)['path']]=copy.deepcopy(paths[path])
            elif kind=='Table':
                path=scalar(props.get('DataPath'))
                if path not in getattr(paths,'tables',set()):raise ValueError('Unknown Table DataPath')
                from v8unpack_backend import table_offsets
                offsets=table_offsets(entry);entry[offsets['path']]=copy.deepcopy(paths[path])
                if 'RowFilter' in props:
                    rowfilter=props['RowFilter']
                    if len(rowfilter) or (rowfilter.text or '').strip() or rowfilter.attrib!={'{http://www.w3.org/2001/XMLSchema-instance}nil':'true'}:raise ValueError('Only an empty table RowFilter is supported')
                nested=props.get('ChildItems')
                if nested is None:nested=E.Element(Q+'ChildItems')
                child_entries=build(nested,depth+1,path);child_index=offsets['children'];_,_,old_end=collection(entry,child_index)
                entry[child_index]=s.atom(len(child_entries)//2);entry[child_index+1:old_end]=child_entries
                if 'AutoCommandBar' in props:auxiliary(props['AutoCommandBar'],entry,'22','9')
                for key in ('SearchStringAddition','ViewStatusAddition','SearchControlAddition'):
                    if key in props:table_addition(props[key],entry,key,name)
            elif kind in GROUPS:
                nested=props.get('ChildItems')
                if nested is None:nested=E.Element(Q+'ChildItems')
                child_entries=build(nested,depth+1,table_path,kind);child_index=group_children(entry);_,_,old_end=collection(entry,child_index)
                entry[child_index]=s.atom(len(child_entries)//2);entry[child_index+1:old_end]=child_entries
            elif kind in ('LabelDecoration','PictureDecoration'):
                if kind=='PictureDecoration':
                    import picture_xml as picture
                    picture.put(entry,layout['picture_path'],picture.read(props.get('Picture')))
                    for key,setting in layout['properties'].items():picture.put(entry,setting['path'],boolean(props.get(key),setting['default']))
            else:
                if scalar(props.get('Type'),'UsualButton')!='UsualButton':raise ValueError('Unsupported Button type')
                command=scalar(props.get('CommandName'),'')
                if not command.startswith('Form.Command.') or command[len('Form.Command.'):] not in command_ids:raise ValueError('Unknown Button command')
                command_number,command_class=command_ids[command[len('Form.Command.'):]]
                entry[8]=[s.atom(command_number),s.atom(command_class)]
            for key,version in [('ContextMenu','22'),('ExtendedTooltip','12')]:
                if key not in props:continue
                auxiliary(props[key],entry,version)
            rules.apply_properties(entry,kind,props,namespaces,getattr(paths,'references',None))
            rules.apply_events(entry,kind,props.get('Events'))
            if field_header:
                entry[4]=s.atom(len(field_header));entry[5:5]=field_header
            output.extend([s.atom(layout['type']),entry])
        return output
    entries=build(items);form[1][index]=s.atom(len(entries)//2);form[1][index+1:end]=entries
