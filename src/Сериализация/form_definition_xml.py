"""Metadata Form.xml beside Ext/Form.xml: complete verified description."""
import metadata_common_xml
import metadata_context
import xml_namespaces
import copy
from xml.etree import ElementTree as E
import native_metadata as s
import platform_profiles as platforms
import managed_form_profiles as form_profiles

Q='{'+xml_namespaces.MD+'}'


def read(text,kind,platform):
    if not isinstance(text,str) or len(text.encode('utf-8'))>s.MAX_BYTES or '<!DOCTYPE' in text.upper():raise ValueError('Invalid form metadata XML')
    try:root=E.fromstring(text)
    except E.ParseError as error:raise ValueError('Invalid form metadata XML: '+str(error)) from None
    tag='CommonForm' if kind=='CommonForm' else 'Form'
    if root.tag!=Q+'MetaDataObject' or not platforms.xml_attributes(root.attrib,platform) or len(root)!=1 or root[0].tag!=Q+tag:
        raise ValueError('Expected MetaDataObject/'+tag)
    obj=root[0]
    if set(obj.attrib)!={'uuid'} or len(obj)!=1 or obj[0].tag!=Q+'Properties' or obj[0].attrib:raise ValueError('Unsupported form metadata sections')
    oid=metadata_context.guid(obj.get('uuid'));fields={v.tag.removeprefix(Q):v for v in obj[0]}
    if len(fields)!=len(obj[0]) or any(v.tag!=Q+k for k,v in fields.items()):raise ValueError('Duplicate or foreign form metadata property')
    defaults={'FormType':'Managed','IncludeHelpInContents':'false','UseInInterfaceCompatibilityMode':'Any'}
    if kind=='CommonForm':defaults.update(UseStandardCommands='true',ExtendedPresentation='',Explanation='')
    if kind in ('DataProcessor','Report'):defaults.update(ExtendedPresentation='')
    for key,node in fields.items():
        if key in ('Name','Synonym','Comment'):continue
        if key=='UsePurposes':
            xsi='{http://www.w3.org/2001/XMLSchema-instance}type'
            if node.attrib or len(node)!=2 or any(v.tag!='{'+xml_namespaces.CORE+'}Value' or v.attrib!={xsi:'app:ApplicationUsePurpose'} or len(v) for v in node) or [v.text for v in node]!=['PlatformApplication','MobilePlatformApplication']:
                raise ValueError('Unsupported form UsePurposes')
        elif key not in defaults or node.attrib or len(node) or (node.text or '')!=defaults[key]:raise ValueError('Unsupported form metadata property: '+key)
    name,common=metadata_common_xml.read(obj[0],oid,platform)
    return oid,name,common


def convert(raw,text,kind,platform,*,allow_rename=False):
    oid,name,common=read(text,kind,platform)
    docs=s.Parser(raw.decode('utf-8-sig')).documents();previous=form_profiles.common(docs[0],kind)
    if s.val(previous[1][2])!=oid or (s.val(previous[2])!=name and not allow_rename):raise ValueError('Form metadata UUID or name mismatch; rename is unsupported')
    layout=form_profiles.layout(kind)
    baseline=s.Parser(layout['body_template']).documents();form_profiles.replace_common(baseline[0],kind,copy.deepcopy(previous))
    if s.render(baseline)!=s.render(docs):raise ValueError('Source form properties are outside the verified XML profile')
    for index in (2,3,4):previous[index]=copy.deepcopy(common[index])
    return s.native_body_bytes(docs)
