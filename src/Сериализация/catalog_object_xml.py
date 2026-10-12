"""Complete supported Catalog XML, including inline attributes and form references."""
import copy,json,re
from pathlib import Path
from xml.etree import ElementTree as E
import metadata_serializer as s
import constant_serializer as c
from flat_object_serializer import object_xml

Q='{'+c.MD+'}'


def canonical(node):
    return [node.tag,dict(node.attrib),(node.text or '') if not len(node) else (node.text or '').strip(),
            [canonical(v) for v in node]]


def common_xml(props, common):
    E.SubElement(props,Q+'Name').text=s.val(common[2])
    synonym=E.SubElement(props,Q+'Synonym')
    for language,text in s.synonym_value(common[3]):
        item=E.SubElement(synonym,'{'+c.CORE+'}item')
        E.SubElement(item,'{'+c.CORE+'}lang').text=language
        E.SubElement(item,'{'+c.CORE+'}content').text=text
    E.SubElement(props,Q+'Comment').text=s.val(common[4])


def attribute_export(entry):
    common=entry[0][1][1][1];pattern=entry[0][1][1][2]
    if len(pattern)!=2 or s.val(pattern[0])!='Pattern' or s.val(pattern[1][0])!='S':raise ValueError('Only string Attribute XML is implemented')
    node=E.Element(Q+'Attribute',uuid=s.val(common[1][2]));props=E.SubElement(node,Q+'Properties');common_xml(props,common)
    typ=E.SubElement(props,Q+'Type');E.SubElement(typ,'{'+c.CORE+'}Type').text='xs:string'
    qualifiers=E.SubElement(typ,'{'+c.CORE+'}StringQualifiers')
    E.SubElement(qualifiers,'{'+c.CORE+'}Length').text=s.val(pattern[1][1])
    E.SubElement(qualifiers,'{'+c.CORE+'}AllowedLength').text='Variable'
    defaults=json.loads(Path(__file__).with_name('catalog_attribute_xml_defaults.json').read_text(encoding='utf-8'))
    def restore(value):
        tag,attrs,text,children=value;n=E.Element(tag,attrs);n.text=text
        for child in children:n.append(restore(child))
        return n
    for value in defaults.values():props.append(restore(value))
    _,_,rebuilt=attribute_xml(node)
    if s.render(rebuilt)!=s.render(entry):raise ValueError('Source Attribute properties are outside the verified XML profile')
    return node


def export(source,forms,platform):
    """Build complete XML for compatibility operations using the verified profile."""
    layout=json.loads(Path(__file__).with_name('catalog_layout_851.json').read_text(encoding='utf-8'))
    common=source[1][9][1];name=s.val(common[2])
    top=E.Element(Q+'MetaDataObject',version='2.21');obj=E.SubElement(top,Q+'Catalog',uuid=s.val(common[1][2]))
    internal=E.SubElement(obj,Q+'InternalInfo')
    slots=layout['generated_slots']
    for i,category in enumerate(layout.get('generated_categories',('Object','Ref','Selection','List','Manager'))):
        typ=E.SubElement(internal,'{'+c.READABLE+'}GeneratedType',name='Catalog'+category+'.'+name,category=category)
        for field,slot in zip(('TypeId','ValueId'),slots[i*2:i*2+2]):E.SubElement(typ,'{'+c.READABLE+'}'+field).text=s.val(source[1][slot])
    props=E.SubElement(obj,Q+'Properties');common_xml(props,common)
    for key,value in layout['defaults'].items():E.SubElement(props,Q+key).text=value
    input_by=E.SubElement(props,Q+'InputByString')
    for field in layout['input_fields']:E.SubElement(input_by,'{'+c.READABLE+'}Field').text='Catalog.'+name+'.StandardAttribute.'+field
    child=E.SubElement(obj,Q+'ChildObjects')
    for entry in source[6][2:]:child.append(attribute_export(entry))
    reverse={value:key for key,value in forms.items()}
    for oid in source[7][2:]:E.SubElement(child,Q+'Form').text=reverse[s.val(oid)]
    return top


def attribute_xml(node):
    if node.tag!=Q+'Attribute' or set(node.attrib)!={'uuid'} or len(node)!=1 or node[0].tag!=Q+'Properties' or node[0].attrib:
        raise ValueError('Expected inline Attribute/Properties')
    aid=c.guid(node.get('uuid'));props=node[0]
    fields={v.tag.removeprefix(Q):v for v in props}
    if len(fields)!=len(props) or any(v.tag!=Q+k for k,v in fields.items()):raise ValueError('Duplicate or unexpected Attribute property')
    defaults=json.loads(Path(__file__).with_name('catalog_attribute_xml_defaults.json').read_text(encoding='utf-8'))
    for name,value in fields.items():
        if name not in ('Name','Synonym','Comment','Type') and (name not in defaults or canonical(value)!=defaults[name]):
            raise ValueError('Unsupported Attribute property: '+name)
    # Reuse the strict Constant reader for common properties and string qualifiers.
    top=E.Element(Q+'MetaDataObject',version='2.21');obj=E.SubElement(top,Q+'Constant',uuid=aid)
    p=E.SubElement(obj,Q+'Properties')
    for name in ('Name','Synonym','Comment','Type'):
        if name in fields:p.append(copy.deepcopy(fields[name]))
    _,name,raw,_=c.constant_xml(E.tostring(top,encoding='unicode'),'8.5.1.1529')
    native=s.Parser(raw.decode('utf-8-sig')).documents()[0][1][1][1]
    entry=s.Parser(json.loads(Path(__file__).with_name('catalog_attribute_layout_851.json').read_text(encoding='utf-8'))['template']).documents()[0]
    entry[0][1][1][1]=copy.deepcopy(native[1]);entry[0][1][1][2]=copy.deepcopy(native[2])
    return aid,name,entry


def convert(text,platform,source,forms,removed_forms=()):
    if not isinstance(text,str) or len(text.encode('utf-8'))>s.MAX_BYTES or '<!DOCTYPE' in text.upper():raise ValueError('Invalid or oversized Catalog XML')
    try:root=E.fromstring(text)
    except E.ParseError as error:raise ValueError('Invalid Catalog XML: '+str(error)) from None
    obj=root.find(Q+'Catalog')
    if obj is None:raise ValueError('Expected Catalog XML')
    children=obj.find(Q+'ChildObjects');desired=list(children) if children is not None else []
    if children is not None:obj.remove(children)
    oid,name,raw,generated=object_xml(E.tostring(root,encoding='unicode'),platform,'Catalog')
    if obj.find(Q+'InternalInfo') is None:raise ValueError('Existing Catalog XML must contain InternalInfo')
    target=s.Parser(raw.decode('utf-8-sig')).documents()[0]
    if oid!=s.val(source[1][9][1][1][2]) or name!=s.val(source[1][9][1][2]):raise ValueError('Catalog UUID or name mismatch; rename is unsupported')
    if len(source)!=8:raise ValueError('Unsupported source Catalog body')
    # Rebuilding defaults must not overwrite unsupported properties already on the server.
    baseline=copy.deepcopy(target);baseline[1][9]=copy.deepcopy(source[1][9]);baseline[6:8]=copy.deepcopy(source[6:8])
    if s.render(baseline)!=s.render(source):raise ValueError('Source Catalog contains properties outside the verified XML profile')
    entries=[];features=[];names=set();form_ids=[];form_names=set()
    for child in desired:
        if child.tag==Q+'Attribute':
            aid,aname,entry=attribute_xml(child)
            if aid in features or aname.casefold() in names:raise ValueError('Duplicate Attribute UUID or name')
            features.append(aid);names.add(aname.casefold());entries.append(entry)
        elif child.tag==Q+'Form' and not child.attrib and not len(child):
            fname=child.text or ''
            if fname not in forms or fname in form_names:raise ValueError('Unknown or duplicate Catalog Form reference')
            form_names.add(fname);form_ids.append(forms[fname])
        else:raise ValueError('Unsupported Catalog ChildObjects entry: '+child.tag)
    removed=set(removed_forms)
    if set(forms)-set(form_names)!={key for key,value in forms.items() if value in removed} or set(form_names)-set(forms):raise ValueError('Creation or removal of separate forms requires a separate object packet')
    if form_ids!=[s.val(v) for v in source[7][2:] if s.val(v) not in removed]:raise ValueError('Reordering separate forms requires updating their object descriptions')
    # Do not leave existing form bindings pointing at a removed inline attribute.
    old_ids={s.val(v[0][1][1][1][1][2]) for v in source[6][2:]}
    if forms and old_ids-set(features):raise ValueError('Attribute removal with existing forms is not yet supported')
    target[6]=[copy.deepcopy(source[6][0]),s.atom(len(entries))]+entries
    target[7]=[copy.deepcopy(source[7][0]),s.atom(len(form_ids))]+[s.atom(v) for v in form_ids]
    return s.native_body_bytes([target]),features
