"""Whole-file managed interface conversion shared by creation and replacement.

The verified Catalog Object profile includes recursive groups, input fields,
buttons, form commands and selected event bindings.
Unknown XML is rejected rather than discarded. Native data remains the baseline
for properties that have no implemented XML mapping.
"""
import re
from xml.etree import ElementTree as E
import metadata_serializer as s
import managed_form_elements as elements

NS = 'http://v8.1c.ru/8.3/xcf/logform'
CORE = 'http://v8.1c.ru/8.1/data/core'
Q = '{' + NS + '}'


class ObjectPaths(dict):
    """Native paths plus the set of bindings that represent tabular collections."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.tables=set();self.types={};self.references={}


def scalar_type(pattern):
    if isinstance(pattern,list) and len(pattern)==2 and isinstance(pattern[1],list) and pattern[1] and isinstance(pattern[1][0],s.Atom):return s.val(pattern[1][0])
    return None


def tabular_paths(owner,kind,paths):
    import catalog_tabular_xml as tabular
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


def catalog_paths(owner):
    """Resolve XML paths using the parent's native inline attribute UUIDs."""
    result = ObjectPaths({name:s.Parser(value).documents()[0] for name,value in
              [('Object.Code','{2,{1},{-2}}'), ('Object.Description','{2,{1},{-3}}')]})
    result.types.update({'Object.Code':'S','Object.Description':'S'})
    for entry in owner[6][2:]:
        common = entry[0][1][1][1]
        name = 'Object.' + s.val(common[2])
        if name in result:
            raise ValueError('Ambiguous Catalog attribute path')
        result[name] = s.Parser('{2,{1},{0,'+s.val(common[1][2])+'}}').documents()[0]
        result.types[name]=scalar_type(entry[0][1][1][2])
    return tabular_paths(owner,'Catalog',result)


def object_paths(owner,kind):
    if kind=='Catalog':return catalog_paths(owner)
    if kind=='CommonForm':return ObjectPaths()
    if kind in ('DataProcessor','Report'):return ObjectPaths()
    if kind!='Document':raise ValueError('Unsupported form owner kind')
    result=ObjectPaths({name:s.Parser(value).documents()[0] for name,value in
            [('Object.Number','{2,{1},{-2}}'),('Object.Date','{2,{1},{-3}}')]})
    result.types.update({'Object.Number':'S','Object.Date':'D'})
    if owner is not None:
        for entry in owner[5][2:]:
            common=entry[0][1][1][1];name='Object.'+s.val(common[2])
            if name in result:raise ValueError('Ambiguous Document attribute path')
            result[name]=s.Parser('{2,{1},{0,'+s.val(common[1][2])+'}}').documents()[0]
            result.types[name]=scalar_type(entry[0][1][1][2])
    return tabular_paths(owner,'Document',result) if owner is not None else result


def scalar_attributes(form,attrs):
    """Replace the whole scalar attribute collection of a common form."""
    import type_description_xml as types
    if attrs is not None and (attrs.attrib or len(attrs)>256):raise ValueError('Invalid form Attributes')
    entries=[];paths=ObjectPaths();numbers=set();names=set()
    for node in ([] if attrs is None else attrs):
        name=node.get('name','');number=node.get('id','')
        if (node.tag!=Q+'Attribute' or set(node.attrib)!={'name','id'}
                or not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE)
                or not number.isdecimal() or not 1<=int(number)<=2147483647
                or name.casefold() in names or int(number) in numbers
                or len(node)!=1 or node[0].tag!=Q+'Type'):
            raise ValueError('Unsupported or duplicate scalar form attribute')
        names.add(name.casefold());numbers.add(int(number))
        entry=s.Parser('{9,{1},0,"",{1,0},{"Pattern"},{0,{0,{"B",1},0}},{0,{0,{"B",1},0}},{0,0},{0,0},0,0,0,0,{0,0},{0,0}}').documents()[0]
        entry[1]=[s.atom(int(number))];entry[3]=s.atom(name,True);entry[5]=types.read(node[0]);entries.append(entry)
        paths[name]=[s.atom(1),[s.atom(int(number))]]
        paths.types[name]=scalar_type(entry[5])
    previous=int(s.val(form[3][1]))
    form[3][2:2+previous]=entries;form[3][1]=s.atom(len(entries))
    return paths


def interface(raw):
    docs = s.Parser(raw.decode('utf-8-sig')).documents()
    if len(docs) != 1 or len(docs[0]) != 10 or s.val(docs[0][0]) != '4' or s.val(docs[0][1][0]) != '59':
        raise ValueError('Unsupported managed interface layout')
    return docs[0]


def append_attribute(raw, attribute, paths, object_name):
    """Compatibility adapter: build a whole XML document, then use convert()."""
    form = interface(raw); index, count, end = elements.form_collection(form)
    root = E.Element(Q+'Form', version='2.21')
    E.SubElement(root,Q+'UseForFoldersAndItems').text = 'Items'
    E.SubElement(root,Q+'AutoCommandBar',name='FormCommandBar',id='-1')
    items = E.SubElement(root,Q+'ChildItems'); maximum = 0
    reverse = {s.render(value):key for key,value in paths.items()}
    wanted = 'Object.'+attribute
    for i in range(index+1,end,2):
        entry = form[1][i+1]; name = s.val(entry[6]); number = int(s.val(entry[1][0]))
        path = reverse.get(s.render(entry[11]))
        if path is None:
            raise ValueError('Unknown existing field binding')
        if name == attribute or path == wanted:
            raise ValueError('Field already exists')
        maximum = max(maximum, number)
        field = E.SubElement(items,Q+'InputField',name=name,id=str(number))
        E.SubElement(field,Q+'DataPath').text = path
    field = E.SubElement(items,Q+'InputField',name=attribute,id=str(max(20,maximum+10)))
    E.SubElement(field,Q+'DataPath').text = wanted
    attr = E.SubElement(E.SubElement(root,Q+'Attributes'),Q+'Attribute',name='Object',id='1')
    E.SubElement(E.SubElement(attr,Q+'Type'),'{'+CORE+'}Type').text = 'cfg:CatalogObject.'+object_name
    E.SubElement(attr,Q+'MainAttribute').text = 'true'
    return convert(raw,E.tostring(root,encoding='unicode'),paths=paths,object_name=object_name)


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
        usage = root.find(Q+'UseForFoldersAndItems')
        if (kind=='Catalog' and usage is None) or (usage is not None and (kind!='Catalog' or usage.attrib or len(usage) or usage.text!='Items')):
            raise ValueError('Only Catalog item forms are supported by the XML profile')
        bar = root.find(Q+'AutoCommandBar')
        if bar is None or len(bar) or bar.attrib != {'name':'FormCommandBar', 'id':'-1'}:
            raise ValueError('Only the default AutoCommandBar is supported')
        attrs = root.find(Q+'Attributes')
        expected_type = 'cfg:'+kind+'Object.' + (object_name or '')
        if kind=='CommonForm':
            references=getattr(paths,'references',{})
            paths=scalar_attributes(form,attrs);paths.references=references
        elif attrs is None or attrs.attrib or len(attrs) != 1:
            raise ValueError('Expected the sole main Object attribute')
        attr = attrs[0] if kind!='CommonForm' else None
        if kind!='CommonForm' and (attr.tag != Q+'Attribute' or attr.attrib != {'name':'Object', 'id':'1'} or len(attr) != 2):
            raise ValueError('Unsupported form attributes')
        type_node = attr.find(Q+'Type') if attr is not None else None; main = attr.find(Q+'MainAttribute') if attr is not None else None
        if kind!='CommonForm' and (type_node is None or type_node.attrib or len(type_node) != 1
                or type_node[0].tag != '{'+CORE+'}Type' or type_node[0].attrib or len(type_node[0])
                or type_node[0].text != expected_type or main is None or main.attrib or len(main) or main.text != 'true'):
            raise ValueError('Form main Object type does not match its owner')
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
