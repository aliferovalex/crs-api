"""Metadata Form.xml beside Ext/Form.xml: complete verified description."""
import copy,json
from pathlib import Path
from xml.etree import ElementTree as E
import metadata_serializer as s
import constant_serializer as c
import platform_profiles as platforms

Q='{'+c.MD+'}'


def read(text,kind,platform):
    if not isinstance(text,str) or len(text.encode('utf-8'))>s.MAX_BYTES or '<!DOCTYPE' in text.upper():raise ValueError('Invalid form metadata XML')
    try:root=E.fromstring(text)
    except E.ParseError as error:raise ValueError('Invalid form metadata XML: '+str(error)) from None
    tag='CommonForm' if kind=='CommonForm' else 'Form'
    if root.tag!=Q+'MetaDataObject' or not platforms.xml_attributes(root.attrib,platform) or len(root)!=1 or root[0].tag!=Q+tag:
        raise ValueError('Expected MetaDataObject/'+tag)
    obj=root[0]
    if set(obj.attrib)!={'uuid'} or len(obj)!=1 or obj[0].tag!=Q+'Properties' or obj[0].attrib:raise ValueError('Unsupported form metadata sections')
    oid=c.guid(obj.get('uuid'));fields={v.tag.removeprefix(Q):v for v in obj[0]}
    if len(fields)!=len(obj[0]) or any(v.tag!=Q+k for k,v in fields.items()):raise ValueError('Duplicate or foreign form metadata property')
    defaults={'FormType':'Managed','IncludeHelpInContents':'false','UseInInterfaceCompatibilityMode':'Any'}
    if kind=='CommonForm':defaults.update(UseStandardCommands='true',ExtendedPresentation='',Explanation='')
    for key,node in fields.items():
        if key in ('Name','Synonym','Comment'):continue
        if key=='UsePurposes':
            xsi='{http://www.w3.org/2001/XMLSchema-instance}type'
            if node.attrib or len(node)!=2 or any(v.tag!='{'+c.CORE+'}Value' or v.attrib!={xsi:'app:ApplicationUsePurpose'} or len(v) for v in node) or [v.text for v in node]!=['PlatformApplication','MobilePlatformApplication']:
                raise ValueError('Unsupported form UsePurposes')
        elif key not in defaults or node.attrib or len(node) or (node.text or '')!=defaults[key]:raise ValueError('Unsupported form metadata property: '+key)
    top=E.Element(Q+'MetaDataObject',version='2.21');dummy=E.SubElement(top,Q+'Constant',uuid=oid);props=E.SubElement(dummy,Q+'Properties')
    for key in ('Name','Synonym','Comment'):
        if key in fields:props.append(copy.deepcopy(fields[key]))
    typ=E.SubElement(props,Q+'Type');E.SubElement(typ,'{'+c.CORE+'}Type').text='xs:string'
    qualifiers=E.SubElement(typ,'{'+c.CORE+'}StringQualifiers');E.SubElement(qualifiers,'{'+c.CORE+'}Length').text='100';E.SubElement(qualifiers,'{'+c.CORE+'}AllowedLength').text='Variable'
    _,name,raw,_=c.constant_xml(E.tostring(top,encoding='unicode'),platform)
    common=s.Parser(raw.decode('utf-8-sig')).documents()[0][1][1][1][1]
    return oid,name,common


def convert(raw,text,kind,platform):
    oid,name,common=read(text,kind,platform)
    docs=s.Parser(raw.decode('utf-8-sig')).documents();previous=docs[0][1][1][1]
    if s.val(previous[1][2])!=oid or s.val(previous[2])!=name:raise ValueError('Form metadata UUID or name mismatch; rename is unsupported')
    layout=json.loads(Path(__file__).with_name({'Catalog':'catalog_form_layout_851.json','Document':'document_form_layout_851.json','CommonForm':'common_form_layout_851.json'}[kind]).read_text(encoding='utf-8'))
    baseline=s.Parser(layout['body_template']).documents();baseline[0][1][1][1]=copy.deepcopy(previous)
    if s.render(baseline)!=s.render(docs):raise ValueError('Source form properties are outside the verified XML profile')
    for index in (2,3,4):previous[index]=copy.deepcopy(common[index])
    return s.native_body_bytes(docs)
