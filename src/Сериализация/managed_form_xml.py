"""Whole-file managed interface conversion shared by creation and replacement.

The first verified XML profile is a flat Catalog Object form with InputFields.
Unknown XML is rejected rather than discarded. Native data remains the baseline
for properties that have no implemented XML mapping.
"""
import copy
import json
import re
from pathlib import Path
from xml.etree import ElementTree as E
import metadata_serializer as s

NS = 'http://v8.1c.ru/8.3/xcf/logform'
CORE = 'http://v8.1c.ru/8.1/data/core'
Q = '{' + NS + '}'


def catalog_paths(owner):
    """Resolve XML paths using the parent's native inline attribute UUIDs."""
    result = {name:s.Parser(value).documents()[0] for name,value in
              [('Object.Code','{2,{1},{-2}}'), ('Object.Description','{2,{1},{-3}}')]}
    for entry in owner[6][2:]:
        common = entry[0][1][1][1]
        name = 'Object.' + s.val(common[2])
        if name in result:
            raise ValueError('Ambiguous Catalog attribute path')
        result[name] = s.Parser('{2,{1},{0,'+s.val(common[1][2])+'}}').documents()[0]
    return result


def interface(raw):
    docs = s.Parser(raw.decode('utf-8-sig')).documents()
    if len(docs) != 1 or len(docs[0]) != 10 or s.val(docs[0][0]) != '4' or s.val(docs[0][1][0]) != '59':
        raise ValueError('Unsupported managed interface layout')
    return docs[0]


def controls(form):
    layout = json.loads(Path(__file__).with_name('managed_form_field_layout_851.json').read_text(encoding='utf-8'))
    props = form[1]; candidates = []
    for index in (23, 25):
        if index >= len(props) or isinstance(props[index], list):
            continue
        try:
            count = int(s.val(props[index]))
        except ValueError:
            continue
        end = index + 1 + count * 2
        if not 0 <= count <= 256 or end >= len(props):
            continue
        if all(not isinstance(props[i], list) and s.val(props[i]) == layout['element_type']
               and isinstance(props[i+1], list) and s.val(props[i+1][0]) == '48'
               for i in range(index+1, end, 2)):
            candidates.append((index, count, end))
    if len(candidates) != 1:
        raise ValueError('Unsupported or ambiguous control collection')
    return candidates[0], layout


def rename(control, name):
    previous = s.val(control[6])
    control[6] = s.atom(name, True)
    for value in control:
        if (isinstance(value,list) and len(value)>6 and not isinstance(value[0],list)
                and s.val(value[0]) in ('12','22') and not isinstance(value[6],list)
                and s.val(value[6]).startswith(previous)):
            value[6] = s.atom(name+s.val(value[6])[len(previous):], True)


def append_attribute(raw, attribute, paths, object_name):
    """Compatibility adapter: build a whole XML document, then use convert()."""
    form = interface(raw); (index, count, end), _ = controls(form)
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


def convert(raw, form_xml=None, module_text=None, paths=None, object_name=None):
    """Return the complete native .0 stream; omitted module preserves source."""
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
        allowed = {'UseForFoldersAndItems', 'AutoCommandBar', 'ChildItems', 'Attributes'}
        seen = set()
        for child in root:
            if child.tag not in {Q+n for n in allowed} or child.tag in seen:
                raise ValueError('Unsupported or duplicate Form.xml section: ' + child.tag)
            seen.add(child.tag)
        usage = root.find(Q+'UseForFoldersAndItems')
        if usage is None or usage.attrib or len(usage) or usage.text != 'Items':
            raise ValueError('Only Catalog item forms are supported by the XML profile')
        bar = root.find(Q+'AutoCommandBar')
        if bar is None or len(bar) or bar.attrib != {'name':'FormCommandBar', 'id':'-1'}:
            raise ValueError('Only the default AutoCommandBar is supported')
        attrs = root.find(Q+'Attributes')
        expected_type = 'cfg:CatalogObject.' + (object_name or '')
        if attrs is None or attrs.attrib or len(attrs) != 1:
            raise ValueError('Expected the sole main Object attribute')
        attr = attrs[0]
        if attr.tag != Q+'Attribute' or attr.attrib != {'name':'Object', 'id':'1'} or len(attr) != 2:
            raise ValueError('Unsupported form attributes')
        type_node = attr.find(Q+'Type'); main = attr.find(Q+'MainAttribute')
        if (type_node is None or type_node.attrib or len(type_node) != 1
                or type_node[0].tag != '{'+CORE+'}Type' or type_node[0].attrib or len(type_node[0])
                or type_node[0].text != expected_type or main is None or main.attrib or len(main) or main.text != 'true'):
            raise ValueError('Form main Object type does not match its Catalog')
        items = root.find(Q+'ChildItems')
        if items is None or items.attrib or len(items) > 256:
            raise ValueError('Invalid or missing ChildItems')
        (index, count, end), layout = controls(form)
        existing = {int(s.val(form[1][i+1][1][0])): form[1][i+1] for i in range(index+1, end, 2)}
        if len(existing) != count:
            raise ValueError('Duplicate native control id')
        entries = []; names = set(); numbers = set()
        for field in items:
            name = field.get('name', ''); number = field.get('id', '')
            if (field.tag != Q+'InputField' or set(field.attrib) != {'name','id'}
                    or not re.fullmatch(r'[^\W\d]\w{0,79}', name, re.UNICODE)
                    or not re.fullmatch(r'[1-9][0-9]{0,8}', number)):
                raise ValueError('Unsupported XML control; expected InputField with name and positive id')
            number = int(number)
            if name.casefold() in names or number in numbers:
                raise ValueError('Duplicate XML control name or id')
            names.add(name.casefold()); numbers.add(number)
            field_seen = set()
            for child in field:
                if child.tag not in {Q+'DataPath', Q+'ContextMenu', Q+'ExtendedTooltip'} or child.tag in field_seen:
                    raise ValueError('Unsupported or duplicate InputField property: '+child.tag)
                field_seen.add(child.tag)
                if child.tag != Q+'DataPath' and (len(child) or set(child.attrib) != {'name','id'}):
                    raise ValueError('Unsupported auxiliary control')
            path = field.find(Q+'DataPath')
            if path is None or path.attrib or len(path) or path.text not in (paths or {}):
                raise ValueError('Unknown InputField DataPath')
            entry = copy.deepcopy(existing.get(number))
            if entry is None:
                entry = s.Parser(layout['template']).documents()[0]
            rename(entry, name); entry[1][0] = s.atom(number)
            entry[11] = copy.deepcopy(paths[path.text])
            # XML auxiliary ids are generated by Designer, but their names are explicit.
            for child in field:
                if child.tag in (Q+'ContextMenu',Q+'ExtendedTooltip'):
                    # Locate the native named subcontrol without assuming its variable offset.
                    version = '22' if child.tag == Q+'ContextMenu' else '12'
                    matches = [v for v in entry if isinstance(v,list) and len(v)>6 and s.val(v[0])==version
                               and (version != '22' or s.val(v[5]) == '8') and s.val(v[6]).startswith(name)]
                    if len(matches) != 1:
                        raise ValueError('Unsupported auxiliary native layout')
                    matches[0][6] = s.atom(child.get('name'), True)
            entries.extend([s.atom(layout['element_type']), entry])
        form[1][index] = s.atom(len(items)); form[1][index+1:end] = entries
    if module_text is not None:
        if not isinstance(module_text, str) or '\0' in module_text or len(module_text.encode('utf-8')) > s.MAX_BYTES:
            raise ValueError('Oversized or invalid form module')
        module_text = module_text.removeprefix('\ufeff').replace('\r\n','\n').replace('\r','\n').replace('\n','\r\n')
        form[2] = s.atom(module_text, True)
    if form_xml is None and module_text is None:
        return raw
    return s.native_body_bytes([form])
