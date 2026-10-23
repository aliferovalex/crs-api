"""Resolve form reference types through version-checked native metadata bodies."""
import metadata_context
import re
from xml.etree import ElementTree as E
import native_metadata as s
import metadata_identifiers as ids

Q='{http://v8.1c.ru/8.3/xcf/logform}'
CORE='{http://v8.1c.ru/8.1/data/core}'
KINDS={'CatalogRef':'Catalog','DocumentRef':'Document','EnumRef':'Enum','DefinedType':'DefinedType'}


def required(xml):
    if xml is None:return set()
    if not isinstance(xml,str) or len(xml.encode('utf-8'))>s.MAX_BYTES or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():raise ValueError('Invalid reference type XML')
    result=set()
    root=E.fromstring(xml)
    for attr in list(root.iter(Q+'Attribute'))+list(root.iter(Q+'Column')):
        if attr.find(Q+'MainAttribute') is not None:continue
        node=attr.find(Q+'Type')
        if node is None:continue
        for child in node:
            value=child.text or ''
            if child.tag not in (CORE+'Type',CORE+'TypeSet') or not value.startswith('cfg:'):continue
            reference_name(value);result.add(value)
    return result


def reference_name(value):
    match=re.fullmatch(r'cfg:([^\.]+)\.([^\W\d]\w{0,79})',value,re.UNICODE)
    if match is None or match[1] not in KINDS:raise ValueError('Unsupported form reference type: '+value)
    return KINDS[match[1]],match[2]


def objects_for_xml(xml,request):
    refs=required(xml)
    if not refs:return refs,{}
    wanted={reference_name(ref) for ref in refs};selected={}
    for oid,docs in metadata_context.context_objects(request['context']).items():
        m=docs[0];kind=ids.class_labels().get(s.val(m[2]));key=(kind,s.val(m[9]))
        if key in wanted:
            if key in selected:raise ValueError('Ambiguous form reference type in context')
            selected[key]=(oid,m)
    if set(selected)!=wanted:raise ValueError('Referenced type is missing from current context')
    return refs,selected


def generated_type(body,metadata,kind):
    import metadata_targets
    return generated_identity(body,metadata_targets.index({s.val(metadata[1]):[metadata]}).targets[0],kind)


def generated_identity(body,identity,kind):
    import native_references,object_xml_profiles
    if identity.class_id!=ids.class_id(kind):raise ValueError('Reference type body/metadata identity mismatch')
    layout=object_xml_profiles.layout(kind)
    generated=native_references.generated_ids(s.native_body_bytes([body]),identity,layout)
    categories=layout.get('generated_categories',('Object','Ref','Selection','List','Manager'))
    return generated[list(categories).index(layout.get('reference_category','Ref'))*2]


def resolve(xml,request,storage=None):
    import native_references
    refs=required(xml)
    if not refs:return {}
    source=native_references.catalog(dict(request,platform=request.get('platform','8.5.1.1529')));resolved={}
    for key in {reference_name(ref) for ref in refs}:
        resolved[key]=source.type_id(*key,storage=storage)
    return {ref:resolved[reference_name(ref)] for ref in refs}
