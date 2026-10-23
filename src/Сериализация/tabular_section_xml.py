"""Inline TabularSection XML driven by verified owner profiles."""
import copy,json
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as E
import native_metadata as s
import metadata_identifiers as ids

Q='{http://v8.1c.ru/8.3/MDClasses}';XR='{http://v8.1c.ru/8.3/xcf/readable}'


@lru_cache(maxsize=1)
def kinds():
    import object_xml_profiles
    return tuple(kind for kind in object_xml_profiles.profiles() if Path(__file__).with_name(kind.lower()+'_tabular_layout_851.json').is_file())


def layout(kind='Catalog'):
    if kind not in kinds():raise ValueError('Unsupported tabular owner kind')
    return json.loads(Path(__file__).with_name(kind.lower()+'_tabular_layout_851.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def attribute_collection_ids():
    return frozenset(layout(kind)['attribute_collection_id'] for kind in kinds())


def collection(source,kind='Catalog'):
    profile=layout(kind);row=source[profile.get('slot',5)]
    if not isinstance(row,list) or len(row)<2 or s.val(row[0])!=profile['collection_id'] or int(s.val(row[1]))!=len(row)-2:raise ValueError('Unsupported tabular section collection')
    return row[2:]


def common(entry):
    try:
        if len(entry)!=3 or (s.val(entry[0][0]),len(entry[0])) not in (('2',3),('2',4),('1',4),('0',2)) or len(entry[0][1])!=9 or s.val(entry[0][1][0])!='11' or s.val(entry[1])!='1':raise ValueError('Unsupported TabularSection layout')
        return entry[0][1][5][1]
    except (IndexError,TypeError):raise ValueError('Unsupported TabularSection layout') from None


def attributes(entry):
    common(entry);row=entry[2]
    if not isinstance(row,list) or len(row)<2 or s.val(row[0]) not in attribute_collection_ids() or int(s.val(row[1]))!=len(row)-2:raise ValueError('Unsupported TabularSection Attribute collection')
    return row[2:]


def feature_ids(entry):
    return [s.val(common(entry)[1][2])]+[s.val(a[0][1][1][1][1][2]) for a in attributes(entry)]


def read(node,owner_name,previous=None,kind='Catalog',*,type_references=None):
    from inline_attribute_xml import attribute_xml
    from metadata_common_xml import canonical
    from metadata_context import guid
    import metadata_common_xml as common_xml
    if node.tag!=Q+'TabularSection' or set(node.attrib)!={'uuid'} or len({v.tag for v in node})!=len(node) or any(v.tag not in (Q+'InternalInfo',Q+'Properties',Q+'ChildObjects') or v.attrib for v in node):raise ValueError('Unsupported TabularSection XML')
    oid=guid(node.get('uuid'));props=node.find(Q+'Properties');internal=node.find(Q+'InternalInfo');children=node.find(Q+'ChildObjects')
    if props is None or internal is None or len(internal)!=2:raise ValueError('TabularSection requires Properties and two generated types')
    fields={v.tag.removeprefix(Q):v for v in props}
    if len(fields)!=len(props) or any(v.tag!=Q+k for k,v in fields.items()):raise ValueError('Duplicate or foreign TabularSection property')
    data=layout(kind)
    for key,value in fields.items():
        if key not in ('Name','Synonym','Comment') and (key not in data['defaults'] or canonical(value)!=data['defaults'][key]):raise ValueError('Unsupported TabularSection property: '+key)
    name,native_common=common_xml.read(props,oid)
    generated=[]
    import object_xml_profiles
    owner_kind=object_xml_profiles.xml_kind(kind)
    for xml,(prefix,category) in zip(internal,[(owner_kind+'TabularSection.','TabularSection'),(owner_kind+'TabularSectionRow.','TabularSectionRow')]):
        if xml.tag!=XR+'GeneratedType' or xml.attrib!={'name':prefix+owner_name+'.'+name,'category':category} or [v.tag for v in xml]!=[XR+'TypeId',XR+'ValueId'] or any(v.attrib or len(v) for v in xml):raise ValueError('Unsupported TabularSection generated type')
        generated.extend(guid(v.text) for v in xml)
    if len(set(generated+[oid]))!=5:raise ValueError('Duplicate TabularSection generated UUID')
    if previous is not None and generated!=[s.val(v) for v in previous[0][1][1:5]]:raise ValueError('Existing TabularSection generated UUIDs must remain unchanged')
    entry=s.Parser(data['template']).documents()[0];entry[0][1][5][1]=copy.deepcopy(native_common)
    for i,value in enumerate(generated,1):entry[0][1][i]=s.atom(value)
    rows=[];features=[oid];names=set()
    for child in children if children is not None else []:
        aid,aname,attr=attribute_xml(child,data['attribute_template'],type_references=type_references,filling=data.get('attribute_filling',False),property_names=data.get('attribute_properties'))
        if aid in features or aid in generated or aname.casefold() in names:raise ValueError('Duplicate tabular Attribute UUID or name')
        features.append(aid);names.add(aname.casefold());rows.append(attr)
    entry[2]=[s.atom(data['attribute_collection_id']),s.atom(len(rows))]+rows
    return oid,name,entry,features,generated


def export(entry,owner_name,kind='Catalog',*,type_references=None):
    from inline_attribute_xml import attribute_export
    from metadata_common_xml import write as common_xml
    data=layout(kind);properties=common(entry);oid=s.val(properties[1][2]);name=s.val(properties[2])
    node=E.Element(Q+'TabularSection',uuid=oid);internal=E.SubElement(node,Q+'InternalInfo')
    values=[s.val(v) for v in entry[0][1][1:5]]
    import object_xml_profiles
    owner_kind=object_xml_profiles.xml_kind(kind)
    for i,(prefix,category) in enumerate([(owner_kind+'TabularSection.','TabularSection'),(owner_kind+'TabularSectionRow.','TabularSectionRow')]):
        typ=E.SubElement(internal,XR+'GeneratedType',name=prefix+owner_name+'.'+name,category=category)
        for key,value in zip(('TypeId','ValueId'),values[i*2:i*2+2]):E.SubElement(typ,XR+key).text=value
    props=E.SubElement(node,Q+'Properties');common_xml(props,properties)
    def restore(value):
        tag,attrs,text,children=value;n=E.Element(tag,attrs);n.text=text
        for child in children:n.append(restore(child))
        return n
    for value in data['defaults'].values():props.append(restore(value))
    children=E.SubElement(node,Q+'ChildObjects')
    for attr in attributes(entry):children.append(attribute_export(attr,data['attribute_template'],type_references=type_references,filling=data.get('attribute_filling',False),property_names=data.get('attribute_properties')))
    _,_,rebuilt,_,_=read(node,owner_name,entry,kind,type_references=type_references)
    if s.render(rebuilt)!=s.render(entry):raise ValueError('Source TabularSection is outside the verified XML profile')
    return node
