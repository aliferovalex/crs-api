"""Final XDTO declarations from whole export files or version-verified storage."""
import base64,hashlib,re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as E
import native_metadata as s
import metadata_context
import metadata_identifiers as ids
import metadata_targets
import object_xml_profiles as profiles
import serialization_context as contexts
import xml_namespaces
import xdto_type_xml

Q='{'+xml_namespaces.MD+'}'
XDTO='http://v8.1c.ru/8.1/xdto'


@dataclass(frozen=True)
class Package:
    object_id: str
    name: str
    namespace: str
    types: frozenset
    imports: frozenset
    digest: str


def declaration(definition,raw):
    if not isinstance(raw,bytes) or len(raw)>s.MAX_BYTES or b'<!DOCTYPE' in raw.upper():raise ValueError('Invalid XDTO package XML')
    if not isinstance(definition,str) or '<!DOCTYPE' in definition.upper():raise ValueError('Invalid XDTO metadata XML')
    try:top=E.fromstring(definition);package=E.fromstring(raw)
    except (E.ParseError,ValueError,LookupError):raise ValueError('Invalid XDTO package XML') from None
    if top.tag!=Q+'MetaDataObject' or len(top)!=1 or top[0].tag!=Q+'XDTOPackage':raise ValueError('Expected XDTOPackage metadata')
    oid=metadata_context.guid(top[0].get('uuid'));name=top[0].findtext(Q+'Properties/'+Q+'Name');namespace=top[0].findtext(Q+'Properties/'+Q+'Namespace')
    if not name or not namespace or package.tag!='{'+XDTO+'}package' or package.get('targetNamespace')!=namespace:raise ValueError('XDTO package namespace differs from metadata')
    names=set();imports=set()
    for node in package:
        if node.tag in ('{'+XDTO+'}valueType','{'+XDTO+'}objectType'):
            value=node.get('name','')
            if not re.fullmatch(r'[^\W\d][\w.-]*',value) or value in names:raise ValueError('Missing or duplicate XDTO type declaration')
            names.add(value)
        elif node.tag=='{'+XDTO+'}import':
            value=node.get('namespace','')
            if not value or value in imports:raise ValueError('Missing or duplicate XDTO import namespace')
            imports.add(value)
    return Package(oid,name,namespace,frozenset(names),frozenset(imports),hashlib.sha256(raw).hexdigest())


class Catalog:
    def __init__(self,packages=()):
        self.packages={};self.namespaces={}
        for package in packages:self.add(package)

    def add(self,package):
        if not isinstance(package,Package):raise ValueError('Invalid XDTO package declaration')
        if package.namespace in xdto_type_xml.types():raise ValueError('User XDTO package shadows a system namespace')
        other=self.namespaces.get(package.namespace)
        if other is not None and other!=package.object_id:raise ValueError('Ambiguous XDTO package namespace')
        previous=self.packages.get(package.object_id)
        if previous is not None:self.namespaces.pop(previous.namespace,None)
        self.packages[package.object_id]=package;self.namespaces[package.namespace]=package.object_id

    def dependencies(self,oid):
        if oid not in self.packages:raise ValueError('Selected XDTO package is missing')
        package=self.packages[oid];result=set()
        for uri in package.imports:
            if uri in xdto_type_xml.types() or uri==package.namespace:continue
            if uri not in self.namespaces:raise ValueError('Unresolved XDTO package import: '+uri)
            result.add(self.namespaces[uri])
        return result

    def available(self,selected):
        pending=list(selected);seen=set();result={uri:frozenset(names) for uri,names in xdto_type_xml.types().items()}
        while pending:
            oid=pending.pop()
            if oid in seen:continue
            seen.add(oid);pending.extend(self.dependencies(oid));package=self.packages[oid];result[package.namespace]=package.types
        return result

    def validate(self):
        for oid in self.packages:self.dependencies(oid)

    def web_types(self,text,objects):
        import metadata_value_list_xml
        top,scopes=xml_namespaces.parse(text);rule=profiles.layout('WebService')['reference_lists']['XDTOPackages']
        selected,_=metadata_value_list_xml.read(top[0].find(Q+'Properties/'+Q+'XDTOPackages'),rule,objects,scopes)
        return self.available(selected)


def from_export(directory,inventory):
    packages=[]
    for record in inventory.values():
        if record['kind']!='XDTOPackage':continue
        file=Path(directory)/record['path'];companion=file.with_suffix('')/'Ext/Package.bin'
        if not companion.is_file() or companion.stat().st_size>s.MAX_BYTES:raise ValueError('Missing or oversized XDTO package file')
        packages.append(declaration(file.read_text(encoding='utf-8-sig'),companion.read_bytes()))
    return Catalog(packages)


def from_storage(request):
    import native_references,metadata_object_xml
    reader=native_references.Catalog(request);wanted=[row for row in reader.targets.targets if row.class_id==ids.class_id('XDTOPackage')]
    if not wanted:return Catalog()
    if 'storage' not in request:raise ValueError('XDTO references require current version storage')
    storage=contexts.decode(request['storage'],'Invalid XDTO version storage');records=reader.source_files(wanted,storage,label='XDTO');packages=[]
    for identity in wanted:
        oid=identity.object_id;record=records[oid];body=s.Parser(record.body.decode('utf-8-sig')).documents()[0]
        definition=metadata_object_xml.export(body,{},request['platform'],'XDTOPackage')
        if definition[0].get('uuid')!=oid or definition[0].findtext(Q+'Properties/'+Q+'Name')!=identity.name:raise ValueError('XDTO body/metadata identity mismatch')
        if oid+'.0' not in record.files:raise ValueError('Missing XDTO package stream')
        packages.append(declaration(xml_namespaces.serialize(definition),record.files[oid+'.0']))
    return Catalog(packages)


def internal(request):
    value=request.get('_xdto_catalog')
    if value is not None and not isinstance(value,Catalog):raise ValueError('Invalid internal XDTO catalog')
    return value


def required(text):
    top,scopes=xml_namespaces.parse(text)
    if len(top)!=1 or top[0].tag!=Q+'WebService':return set()
    return {xdto_type_xml.name(node,scopes) for node in top.iter() if node.tag in (Q+'XDTOReturningValueType',Q+'XDTOValueType')}


def needs_storage(text,context,complete=False):
    top=E.fromstring(text)
    if len(top)!=1:return False
    objects=metadata_context.context_objects(context);oid=top[0].get('uuid');kind=top[0].tag
    packages={key for key,docs in objects.items() if s.val(docs[0][2])==ids.class_id('XDTOPackage')}
    if kind==Q+'XDTOPackage':
        if complete:return oid in objects and any(s.metadata_relations(objects[oid][0][14]).get(key)==0 for key in packages-{oid})
        return bool(packages-{oid}) or any(s.metadata_relations(docs[0][14]).get(oid)==0 for docs in objects.values())
    return not complete and kind==Q+'WebService' and bool(packages) and any(uri not in xdto_type_xml.types() for uri,_ in required(text))


def for_web(text,request,objects=None):
    refs=required(text)
    if not refs:return None
    catalog=internal(request)
    if catalog is None and all(uri in xdto_type_xml.types() for uri,_ in refs):return None
    if catalog is None:catalog=from_storage(request)
    return catalog.web_types(text,objects if objects is not None else metadata_context.context_objects(request['context']))


def for_package(request,definition,data):
    encoded=data.get('Package') if isinstance(data,dict) else None
    if not isinstance(encoded,str) or len(encoded)>s.MAX_BYTES*2:raise ValueError('Missing or oversized companion file data')
    package=declaration(definition,base64.b64decode(encoded,validate=True));catalog=internal(request)
    if catalog is not None:
        if catalog.packages.get(package.object_id)!=package:raise ValueError('XDTO package differs from final declaration')
    else:
        source=metadata_context.context_objects(request['context']);own=package.object_id
        others={oid for oid,docs in source.items() if s.val(docs[0][2])==ids.class_id('XDTOPackage')}-{own}
        dependents={oid for oid,docs in source.items() if s.metadata_relations(docs[0][14]).get(own)==0}
        catalog=from_storage(request) if others or dependents else Catalog()
        previous=catalog.packages.get(own)
        if dependents and previous is not None and previous.digest!=package.digest:raise ValueError('Changes to a referenced XDTO package require a complete export')
        catalog.add(package)
    source=metadata_context.context_objects(request['context']);managed=set()
    if package.object_id in source:
        candidates={oid for oid,docs in source.items() if oid!=package.object_id and s.val(docs[0][2])==ids.class_id('XDTOPackage') and s.metadata_relations(source[package.object_id][0][14]).get(oid)==0}
        if candidates:
            previous=from_storage(request);old=previous.packages[package.object_id]
            managed={previous.namespaces[uri] for uri in old.imports if uri in previous.namespaces and previous.namespaces[uri]!=package.object_id}&candidates
    return catalog,catalog.dependencies(package.object_id),managed
