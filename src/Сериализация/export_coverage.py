"""Read-only proof that owned CF assets were represented in a full XML export.

This checks representation and compound-file completeness, not XML property
equivalence. ibcmd's complete reverse-export comparison remains a separate step.
"""
import base64
import io
from pathlib import PurePosixPath as Path
import re
import struct
import xml.etree.ElementTree as ET

import cf_container
import native_metadata as s
import native_predefined_reader
import native_streams
import metadata_structure
import native_configuration_reader
from configuration_export import folder

Q='{http://v8.1c.ru/8.3/MDClasses}'
XR='{http://v8.1c.ru/8.3/xcf/readable}'


def _group(raw):
    docs=s.Parser(raw.decode('utf-8-sig')).documents()
    if len(docs)!=1 or not isinstance(docs[0],list):
        raise ValueError('Expected one native asset record')
    return docs[0]


def _module(raw):
    """Return text or None for a protected/binary representation."""
    container_header=raw.startswith(b'\xff\xff\xff\x7f')
    if not container_header and len(raw)>=20:
        _,block,count,reserved=struct.unpack('<Qiii',raw[:20])
        container_header=0<block<=65536 and block&(block-1)==0 and count>=0 and reserved==0
    if container_header:
        stream=io.BytesIO(raw);container=cf_container.detect_format(stream);container.read(stream)
        if 'text' not in container.files:return None
        raw=b''.join(container.files['text'].data)
    elif not raw.startswith(b'\xef\xbb\xbf'):
        return None
    try:
        text=raw.decode('utf-8-sig')
        if not container_header and text.lstrip().startswith(('<','{','[')):return None
        return text
    except UnicodeDecodeError:return None


def _form_module(raw):
    """Read the third outer slot without interpreting the interface tree.

    Interfaces may contain empty native fields which the metadata parser does
    not support. Their element/property layout is irrelevant to this check.
    """
    text=raw.decode('utf-8-sig').strip()
    if not re.match(r'^\{\s*[34]\s*,',text):raise ValueError('Unsupported native managed form bundle')
    depth=0;separators=0
    for token in re.finditer(r'"(?:""|[^"])*"|[{},]',text):
        value=token.group()
        if value=='{':depth+=1
        elif value=='}':depth-=1
        elif value==',' and depth==1:
            separators+=1
            if separators==2:
                parser=s.Parser(text);parser.pos=token.end();module=parser.value()
                if not isinstance(module,s.Atom) or not module.quoted:break
                return s.val(module)
        if depth<=0:break
    raise ValueError('Unsupported native managed form module slot')


def _owners(records):
    """Include root feature and inline child owners, not only separate XMLs."""
    owners=dict(records)
    def add(oid,record):
        if oid in owners and owners[oid] is not record:raise ValueError('Duplicate native asset owner: '+oid)
        owners[oid]=record
    def children(record,node,path):
        rules=metadata_structure.profile(record['kind'])['collections']
        for rule in rules:
            if rule['storage']!='inline_xml':continue
            for child in node.findall(Q+'ChildObjects/'+Q+rule['xml_name']):
                oid=child.get('uuid');name=child.findtext(Q+'Properties/'+Q+'Name')
                if not oid or not name:continue
                child_path=str(Path(path).with_suffix('')/folder(rule['xml_name'])/_component(name))+'.xml'
                row=dict(kind=rule['item_type'],path=child_path,node=child)
                add(oid,row);children(row,child,child_path)
    for record in records.values():
        node=record.get('node')
        if node is None:continue
        if record['kind']=='Configuration':
            for feature in node.findall(Q+'InternalInfo/'+XR+'ContainedObject'):
                if feature.findtext(XR+'ClassId')==native_configuration_reader.ROOT_FEATURE_CLASS:
                    add(feature.findtext(XR+'ObjectId'),record)
        children(record,node,record['path'])
    return owners


def _component(value):
    # Refuse a path we cannot map safely instead of guessing a sanitised name.
    if not isinstance(value,str) or not value or value in ('.','..') or re.search(r'[<>:"/\\|?*\x00-\x1f]',value):
        raise ValueError('Unsupported native asset filename: '+repr(value))
    return value


def _help(raw,path,files,require):
    fields=_group(raw)
    if len(fields)<2 or s.val(fields[0])!='5':raise ValueError('Unsupported native help record')
    count=int(s.val(fields[1]));pos=2;pages=[];attachments=[]
    if count<0 or count>(len(fields)-2)//2:raise ValueError('Invalid native help page count')
    def payload(node):
        if not isinstance(node,list) or len(node)!=1:raise ValueError('Invalid native help payload')
        token=s.val(node[0])
        if not token.startswith('#base64:'):raise ValueError('Invalid native help payload')
        base64.b64decode(''.join(token[8:].split()),validate=True)
    for _ in range(count):
        language=fields[pos]
        if not isinstance(language,s.Atom) or not language.quoted:raise ValueError('Invalid help language')
        pages.append(_component(s.val(language)));payload(fields[pos+1]);pos+=2
    if pos<len(fields):
        size=int(s.val(fields[pos]));pos+=1
        if size<0 or size>(len(fields)-pos)//2:raise ValueError('Invalid help attachment count')
        for _ in range(size):
            name=fields[pos]
            if not isinstance(name,s.Atom) or not name.quoted:raise ValueError('Invalid help attachment name')
            attachments.append(_component(s.val(name)));pos+=1
            if pos<len(fields) and isinstance(fields[pos],s.Atom) and s.val(fields[pos]).isdigit():pos+=1
            payload(fields[pos]);pos+=1
    if pos!=len(fields):raise ValueError('Unmapped native help fields')
    if len(set(pages))!=len(pages) or len(set(attachments))!=len(attachments):
        raise ValueError('Duplicate native help filenames')
    if not pages and not attachments:return
    require(path)
    exported=ET.fromstring(files[path])
    present={node.text for node in exported.iter() if node.tag.rsplit('}',1)[-1]=='Page'}
    if set(pages)!=present:raise ValueError('Help index differs from native pages: '+path)
    directory=Path(path).with_suffix('')
    for name in [page+'.html' for page in pages]+attachments:require(str(directory/name))


def require_complete_export(image,records,files):
    """Reject missing known assets and unknown nonempty owned streams."""
    records=_owners(records)
    for name,raw in sorted(image.items()):
        owner,separator,suffix=name.partition('.')
        if not separator or not re.fullmatch(r'[0-9a-fA-F-]{36}',owner):continue
        if not raw:continue
        record=records.get(owner)
        if record is None:raise ValueError('Native stream owner is absent from XML export: '+name)
        kind=native_streams.family(record['kind']);route=native_streams.routes(kind).get('.'+suffix)
        if route is None:raise ValueError('Unmapped nonempty native stream: '+kind+' '+name)
        prefix=Path(record['path']).with_suffix('') if kind!='Configuration' else Path('.')
        path=str(prefix/route['path']);codec=route['codec']
        def require(relative):
            if relative not in files:raise ValueError('Compiler omitted native asset from complete XML export: '+relative+' ('+name+')')
        if codec=='Predefined':
            if path not in files and native_predefined_reader.read(raw,kind):
                raise ValueError('Compiler omitted nonempty predefined data from complete XML export: '+path)
        elif codec=='Module':
            text=_module(raw)
            if text is None:require(str(Path(path).with_suffix('.bin')))
            elif text:require(path)
        elif codec=='ManagedForm':
            require(path)
            if _form_module(raw):require(str(Path(path).with_suffix('')/'Module.bsl'))
        elif codec=='Help':_help(raw,path,files,require)
        elif codec=='Picture':
            require(path)
            for node in ET.fromstring(files[path]).iter(XR+'Abs'):
                require(str(Path(path).with_suffix('')/_component(node.text)))
        elif codec=='Template':
            # The definition selects one of these whole-file representations.
            node=record.get('node');template_type=None
            if node is not None:
                template_type=next((n.text for n in node.iter() if n.tag.rsplit('}',1)[-1]=='TemplateType'),None)
            extension={'AddIn':'.bin','BinaryData':'.bin','TextDocument':'.txt',
                       'DataCompositionSchema':'.xml','DataCompositionAppearanceTemplate':'.xml',
                       'GraphicalSchema':'.xml','HTMLDocument':'.xml','SpreadsheetDocument':'.xml'}.get(template_type)
            if extension is None:raise ValueError('Unsupported template export representation: '+str(template_type))
            path+=extension
            if template_type=='HTMLDocument':_help(raw,path,files,require)
            else:require(path)
        elif codec=='CommandInterface' and s.render(_group(raw))=='{7,0,0,0,0,0,0}':
            pass  # Confirmed native empty command interface is deliberately omitted.
        else:require(path)
