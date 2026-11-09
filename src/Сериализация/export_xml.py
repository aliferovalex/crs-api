"""Read complete export files and metadata XML identities."""
import metadata_context
import xml_namespaces
from pathlib import Path
from xml.etree import ElementTree as E
import native_metadata as s

Q='{'+xml_namespaces.MD+'}'
def read(path):
    path=Path(path)
    if not path.is_file() or path.stat().st_size>s.MAX_BYTES:raise ValueError('Missing or oversized export file: '+str(path))
    return path.read_text(encoding='utf-8-sig')


def metadata(text):
    if '<!DOCTYPE' in text.upper():raise ValueError('DOCTYPE is unsupported')
    root=E.fromstring(text)
    if root.tag!=Q+'MetaDataObject' or len(root)!=1:raise ValueError('Expected one metadata object XML, not Ext/Form.xml')
    obj=root[0];kind=obj.tag.removeprefix(Q)
    if obj.tag!=Q+kind or set(obj.attrib)!={'uuid'}:raise ValueError('Invalid metadata XML object')
    oid=metadata_context.guid(obj.get('uuid'));props=obj.findall(Q+'Properties')
    if len(props)!=1:raise ValueError('Missing or duplicate Properties')
    names=props[0].findall(Q+'Name')
    if len(names)!=1 or len(names[0]) or not names[0].text:raise ValueError('Missing or duplicate object Name')
    return kind,oid,names[0].text
