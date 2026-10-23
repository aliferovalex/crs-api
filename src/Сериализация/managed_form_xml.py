"""Whole-file managed interface conversion shared by creation and replacement.

The verified Catalog Object profile includes recursive groups, input fields,
buttons, form commands and selected event bindings.
Unknown XML is rejected rather than discarded. Native data remains the baseline
for properties that have no implemented XML mapping.
"""
import json,re
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as E
import native_metadata as s
import managed_form_elements as elements

NS = 'http://v8.1c.ru/8.3/xcf/logform'
CORE = 'http://v8.1c.ru/8.1/data/core'
Q = '{' + NS + '}'


class ObjectPaths(dict):
    """Native paths plus the set of bindings that represent tabular collections."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.tables=set();self.types={};self.references={};self.main_types={};self.main_collections=set()


def scalar_type(pattern):
    if isinstance(pattern,list) and len(pattern)==2 and isinstance(pattern[1],list) and pattern[1] and isinstance(pattern[1][0],s.Atom):return s.val(pattern[1][0])
    return None


def tabular_paths(owner,kind,paths):
    import tabular_section_xml as tabular
    for entry in tabular.collection(owner,kind):
        common=tabular.common(entry);name='Object.'+s.val(common[2]);oid=s.val(common[1][2])
        if name in paths:raise ValueError('Ambiguous tabular form binding')
        paths[name]=s.Parser('{2,{1},{0,'+oid+'}}').documents()[0];paths.tables.add(name)
        for attr in tabular.attributes(entry):
            common=attr[0][1][1][1];field=name+'.'+s.val(common[2])
            if field in paths:raise ValueError('Ambiguous tabular attribute form binding')
            paths[field]=s.Parser('{3,{1},{0,'+oid+'},{0,'+s.val(common[1][2])+'}}').documents()[0]
            paths.types[field]=scalar_type(attr[0][1][1][2])
    return paths


def object_paths(owner,kind):
    import managed_form_bindings as bindings
    profile=bindings.owners().get(kind,{})
    if 'inline_groups' in profile:
        result=ObjectPaths()
        if owner is not None:
            bindings.attach_types(result,owner,kind);bindings.register_fields(result,owner,kind)
            if profile.get('tabular_sections'):tabular_paths(owner,kind,result)
        return result
    return bindings.attach_types(_object_paths(owner,kind),owner,kind)


def _object_paths(owner,kind):
    if kind=='CommonForm':return ObjectPaths()
    if kind in ('DataProcessor','Report'):return ObjectPaths()
    import managed_form_profiles as profiles
    if kind in profiles.KINDS:return ObjectPaths()
    raise ValueError('Unsupported form owner kind')


@lru_cache(maxsize=1)
def attribute_layout():
    return json.loads(Path(__file__).with_name('managed_form_attribute_layout_851.json').read_text(encoding='utf-8'))


def attribute_identity(node,tag,names,numbers):
    name=node.get('name','');number=node.get('id','')
    if (node.tag!=Q+tag or set(node.attrib)!={'name','id'}
            or not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE)
            or not number.isdecimal() or not 1<=int(number)<=2147483647
            or name.casefold() in names or int(number) in numbers
            or (node.text or '').strip()):
        raise ValueError('Unsupported or duplicate form '+tag)
    names.add(name.casefold());numbers.add(int(number))
    return name,int(number)


def attribute_columns(node,entry,paths,name,number):
    """Rebuild all columns for both intrinsic collection types, including paths."""
    import type_description_xml as types
    if node is not None and (node.attrib or len(node)>256 or (node.text or '').strip()):raise ValueError('Invalid form Columns')
    layout=attribute_layout();names=set();numbers=set();columns=[]
    for column in ([] if node is None else node):
        column_name,column_id=attribute_identity(column,'Column',names,numbers)
        props=elements.fields(column,{'Type','Title'})
        native=s.Parser(layout['column_template']).documents()[0]
        native[1]=s.atom(column_id);native[3]=s.atom(column_name,True);native[4]=elements.title(props.get('Title'))
        native[5]=types.read_form(props.get('Type'),paths.references);columns.append(native)
        path=name+'.'+column_name
        if path in paths:raise ValueError('Ambiguous form column binding')
        paths[path]=[s.atom(2),[s.atom(number)],[s.atom(column_id)]]
        paths.types[path]=scalar_type(native[5])
    entry[layout['column_count_slot']]=s.atom(len(columns))
    entry[layout['columns_slot']:layout['columns_slot']]=columns


def attributes_from_xml(form,attrs,paths=None,main=None,main_type=None):
    """Replace all attributes, retaining the verified native main-object type."""
    import type_description_xml as types
    if attrs is not None and (attrs.attrib or len(attrs)>256 or (attrs.text or '').strip()):raise ValueError('Invalid form Attributes')
    entries=[];numbers=set();names=set()
    result=ObjectPaths(paths or {})
    if paths is not None:
        result.tables.update(getattr(paths,'tables',set()))
        result.types.update(getattr(paths,'types',{}))
        result.references.update(getattr(paths,'references',{}))
        result.main_types.update(getattr(paths,'main_types',{}));result.main_collections.update(getattr(paths,'main_collections',set()))
    previous=int(s.val(form[3][1]))
    main_entry=None
    if main is not None:
        if main_type is None:raise ValueError('Main attribute type context is required')
        main_entry=s.Parser(attribute_layout()['attribute_template']).documents()[0]
        main_entry[5]=[s.atom('Pattern',True),[s.atom('#',True),s.atom(main_type)]];main_entry[10]=s.atom(1)
    for node in ([] if attrs is None else attrs):
        name,number=attribute_identity(node,'Attribute',names,numbers)
        props=elements.fields(node,{'Type','Title','MainAttribute'} if node is main else {'Type','Title','Columns'})
        if node is main:
            main_entry[1]=[s.atom(number)];main_entry[3]=s.atom(name,True)
            main_entry[4]=elements.title(props.get('Title'))
            entries.append(main_entry)
            continue
        layout=attribute_layout();entry=s.Parser(layout['attribute_template']).documents()[0]
        entry[1]=[s.atom(number)];entry[3]=s.atom(name,True);entry[4]=elements.title(props.get('Title'))
        type_node=props.get('Type');collection=None
        if type_node is not None and not type_node.attrib and len(type_node)==1 and type_node[0].tag=='{'+CORE+'}Type' and not type_node[0].attrib and not len(type_node[0]):
            collection=layout['collection_types'].get(type_node[0].text)
        if collection is None:
            if 'Columns' in props:raise ValueError('Columns require a ValueTable or ValueTree attribute')
            entry[5]=types.read_form(type_node,result.references)
        else:
            entry[5]=[s.atom('Pattern',True),[s.atom('#',True),s.atom(collection)]]
            result.tables.add(name);attribute_columns(props.get('Columns'),entry,result,name,number)
        entries.append(entry)
        if name in result:raise ValueError('Ambiguous form attribute binding')
        result[name]=[s.atom(1),[s.atom(number)]]
        result.types[name]=scalar_type(entry[5])
    form[3][2:2+previous]=entries;form[3][1]=s.atom(len(entries))
    return result


def interface(raw):
    docs = s.Parser(raw.decode('utf-8-sig')).documents()
    if len(docs) != 1 or len(docs[0]) != 10 or s.val(docs[0][0]) != '4' or s.val(docs[0][1][0]) != '59':
        raise ValueError('Unsupported managed interface layout')
    return docs[0]


def model_from_xml(raw, form_xml=None, module_text=None, paths=None, object_name=None,kind='Catalog',configuration_id=None):
    """Map the whole XML interface to the upstream form/elem.json model."""
    form = interface(raw)
    if form_xml is not None:
        if not isinstance(form_xml, str) or len(form_xml.encode('utf-8')) > s.MAX_BYTES:
            raise ValueError('Oversized or invalid Form.xml')
        if '<!DOCTYPE' in form_xml.upper() or '<!ENTITY' in form_xml.upper():
            raise ValueError('DTD and entities are not supported in Form.xml')
        try:
            root = E.fromstring(form_xml)
        except E.ParseError as error:
            raise ValueError('Invalid Form.xml: ' + str(error)) from None
        if root.tag != Q+'Form' or root.attrib != {'version': '2.21'}:
            raise ValueError('Expected managed Form.xml version 2.21')
        import managed_form_profiles as profiles
        if kind not in profiles.KINDS:raise ValueError('Unsupported form kind')
        defaults=profiles.defaults(kind)
        allowed = {'UseForFoldersAndItems', 'AutoCommandBar', 'ChildItems', 'Attributes', 'Events', 'Commands'}|set(defaults)
        seen = set()
        for child in root:
            if child.tag not in {Q+n for n in allowed} or child.tag in seen:
                raise ValueError('Unsupported or duplicate Form.xml section: ' + child.tag)
            seen.add(child.tag)
            key=child.tag.removeprefix(Q)
            if key in defaults and (child.attrib or len(child) or child.text!=defaults[key]):raise ValueError('Unsupported document form property: '+key)
        attrs = root.find(Q+'Attributes')
        scalar=kind=='CommonForm' or attrs is None or not any(node.find(Q+'MainAttribute') is not None for node in attrs)
        usage = root.find(Q+'UseForFoldersAndItems')
        import managed_form_bindings
        expected_usage=managed_form_bindings.owners().get(kind,{}).get('form_usage')
        if (expected_usage is not None and not scalar and usage is None) or (usage is not None and (expected_usage is None or usage.attrib or len(usage) or usage.text!=expected_usage)):
            raise ValueError('Unsupported form item/folder usage for owner: '+kind)
        bar = root.find(Q+'AutoCommandBar')
        if bar is None or len(bar) or bar.attrib != {'name':'FormCommandBar', 'id':'-1'}:
            raise ValueError('Only the default AutoCommandBar is supported')
        attrs = root.find(Q+'Attributes')
        main_attrs=[] if attrs is None else [node for node in attrs if node.find(Q+'MainAttribute') is not None]
        if not scalar and len(main_attrs)!=1:raise ValueError('Expected one main attribute')
        attr = main_attrs[0] if not scalar else None
        type_node = attr.find(Q+'Type') if attr is not None else None; main = attr.find(Q+'MainAttribute') if attr is not None else None
        if not scalar and (type_node is None or type_node.attrib or len(type_node) != 1
                or type_node[0].tag != '{'+CORE+'}Type' or type_node[0].attrib or len(type_node[0])
                or main is None or main.attrib or len(main) or main.text != 'true'):
            raise ValueError('Main attribute binding has an unsupported type description')
        main_id=None
        if not scalar:
            import managed_form_bindings as bindings
            name,number=attribute_identity(attr,'Attribute',set(),set());key=type_node[0].text or ''
            main_id=bindings.main_type(paths,form,key,kind,object_name or '')
            paths=bindings.retarget(paths,name,number,key in getattr(paths,'main_collections',set()))
        if scalar:
            scalar_paths=ObjectPaths();scalar_paths.references.update(getattr(paths,'references',{}))
        paths=attributes_from_xml(form,attrs,scalar_paths if scalar else paths,attr,main_id)
        items = root.find(Q+'ChildItems')
        if items is None:items=E.Element(Q+'ChildItems')
        if items.attrib or len(items) > 256:
            raise ValueError('Invalid or missing ChildItems')
        import managed_form_rules as rules
        form_events=root.find(Q+'Events')
        if kind=='Report':
            import report_form_properties
            report_form_properties.apply(form,root,object_name or '',configuration_id)
        rules.apply_events(form,'Form',form_events,kind not in ('DataProcessor','Report'))
        form[5], command_ids = elements.commands(root.find(Q+'Commands'), form[5])
        import appearance_xml
        elements.replace_tree(form, items, paths if paths is not None else {}, command_ids,appearance_xml.namespaces(form_xml))
        if kind not in ('DataProcessor','Report') and any(node.tag==Q+'Events' and len(node) for node in items.iter()):
            rules.add_event_defaults(form,'Form',rules.profiles()['Form']['event_header'])
    if module_text is not None:
        if not isinstance(module_text, str) or '\0' in module_text or len(module_text.encode('utf-8')) > s.MAX_BYTES:
            raise ValueError('Oversized or invalid form module')
        module_text = module_text.removeprefix('\ufeff').replace('\r\n','\n').replace('\r','\n').replace('\n','\r\n')
        form[2] = s.atom(module_text, True)
    from v8unpack_backend import form_model
    return form_model(form)


def convert(raw, form_xml=None, module_text=None, paths=None, object_name=None,kind='Catalog',configuration_id=None):
    """Use upstream form assembly for creation, replacement and module changes."""
    if form_xml is None and module_text is None:return raw
    from v8unpack_backend import assemble_form
    model=model_from_xml(raw,form_xml,module_text,paths,object_name,kind,configuration_id)
    return assemble_form(model)
