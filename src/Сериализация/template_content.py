"""Whole-file template content codecs; metadata and commit framing stay shared."""
import base64
from pathlib import Path
from xml.etree import ElementTree as E
import metadata_serializer as s
import schema_content
import template_references

Q='{http://v8.1c.ru/8.3/MDClasses}'
PROFILES={
    'BinaryData':dict(code=1,file='Template.bin'),
    'TextDocument':dict(code=4,file='Template.txt'),
    'DataCompositionSchema':dict(code=6,file='Template.xml'),
}


def kind(definition):
    root=E.fromstring(definition);node=root[0].find(Q+'Properties/'+Q+'TemplateType')
    if node is None or node.attrib or len(node) or node.text not in PROFILES:
        raise ValueError('Unsupported or missing TemplateType')
    return node.text


def companion(path,definition):
    typ=kind(definition);file=Path(path).with_suffix('')/'Ext'/PROFILES[typ]['file']
    if not file.is_file() or file.stat().st_size>s.MAX_BYTES:raise ValueError('Missing or oversized template companion: '+str(file))
    raw=file.read_bytes()
    if typ=='DataCompositionSchema':return dict(template_xml=raw.decode('utf-8-sig').replace('\r\n','\n').replace('\r','\n'))
    return dict(template_data=base64.b64encode(raw).decode())


def convert(request):
    typ=kind(request['definition_xml'])
    if typ=='DataCompositionSchema':
        types,styles=template_references.resolve(request)
        return schema_content.convert(request['template_xml'],types,styles)
    encoded=request.get('template_data')
    if not isinstance(encoded,str) or len(encoded)>s.MAX_BYTES*2:raise ValueError('Missing or oversized template file data')
    raw=base64.b64decode(encoded,validate=True)
    if len(raw)>s.MAX_BYTES:raise ValueError('Oversized template content')
    if typ=='TextDocument':
        try:raw.decode('utf-8-sig')
        except UnicodeDecodeError:raise ValueError('TextDocument requires UTF-8 text') from None
        return raw
    return s.native_body_bytes([[s.atom(1),[s.atom('#base64:'+base64.b64encode(raw).decode())]]])


def validate_source(raw,definition):
    typ=kind(definition)
    if typ=='DataCompositionSchema':schema_content.unpack(raw);return
    if typ=='TextDocument':
        try:raw.decode('utf-8-sig')
        except UnicodeDecodeError:raise ValueError('Invalid source text template encoding') from None
        return
    docs=s.Parser(raw.decode('utf-8-sig')).documents()
    if len(docs)!=1 or len(docs[0])!=2 or s.val(docs[0][0])!='1' or len(docs[0][1])!=1:
        raise ValueError('Unsupported native binary template')
    token=docs[0][1][0]
    if token.quoted or not s.val(token).startswith('#base64:'):raise ValueError('Unsupported native binary template value')
    base64.b64decode(''.join(s.val(token)[8:].split()),validate=True)
