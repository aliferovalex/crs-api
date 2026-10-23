"""Resolve metadata Type names against source bodies or final declarations."""
import re
import uuid
from xml.etree import ElementTree as E
import native_metadata as s
import native_references
import object_xml_profiles as profiles
import serialization_context as contexts
import type_description_xml as types
import metadata_type_sets as type_sets


def reference_definition(value):
    match=re.fullmatch(r'cfg:([^\.]+)\.([^\W\d]\w{0,79})',value,re.UNICODE)
    candidates=[]
    if match is not None:
        for kind in profiles.profiles():
            rules=profiles.reference_types(kind)
            if match[1] in rules:candidates.append((kind,match[2],rules[match[1]]))
    if len(candidates)!=1:raise ValueError('Unsupported metadata reference type: '+value)
    return candidates[0]


def reference_name(value):
    return reference_definition(value)[:2]


def required(xml):
    if not isinstance(xml,str) or len(xml.encode('utf-8'))>s.MAX_BYTES or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():raise ValueError('Invalid metadata type XML')
    result=set()
    for node in E.fromstring(xml).iter():
        if node.tag not in (types.Q+'Type',types.Q+'TypeSet'):continue
        value=types.text(node)
        if value.startswith('cfg:'):
            if value not in type_sets.profile():reference_name(value)
            result.add(value)
    return result


def resolve(xml,request):
    refs=required(xml)
    if not refs:return {}
    reader=native_references.catalog(request)
    storage=contexts.decode(request['storage'],'Metadata references require current version storage') if 'storage' in request else None
    return {ref:(type_sets.profile()[ref] if ref in type_sets.profile() else reader.type_id(*reference_definition(ref),storage=storage)) for ref in sorted(refs)}


def object_ids(xml,reader):
    refs=required(xml)
    storage=contexts.decode(reader.request['storage'],'Type-set dependencies require current version storage') if 'storage' in reader.request else None
    return {reader.select(*reference_name(ref),label='Referenced type').object_id for ref in refs if ref not in type_sets.profile()}|type_sets.dependencies(refs,reader,storage)


def reference_kinds():
    result=set()
    for kind in profiles.profiles():
        if profiles.reference_types(kind):result.add(kind)
    return result


def needs_storage(xml,context,oid):
    """Removing the last XML reference still requires its source definition."""
    if required(xml):return True
    import metadata_context,metadata_identifiers
    objects=metadata_context.context_objects(context)
    if oid not in objects:return False
    classes={metadata_identifiers.class_id(kind) for kind in reference_kinds()}
    return any(flag==0 and key in objects and s.val(objects[key][0][2]) in classes for key,flag in s.metadata_relations(objects[oid][0][14]).items())


def type_ids(node):
    result=set()
    def visit(value):
        if not isinstance(value,list):return
        if value and not isinstance(value[0],list) and s.val(value[0])=='Pattern':
            for arm in value[1:]:
                if isinstance(arm,list) and arm and s.val(arm[0])=='#':
                    if len(arm)!=2:raise ValueError('Invalid native reference Type pattern')
                    result.add(str(uuid.UUID(s.val(arm[1]))))
        for child in value:visit(child)
    visit(node);return result


def source_owners(request,source,layout,relations,oid,*,strict=True):
    """Prove source dependencies using mapped properties and generated types."""
    import metadata_identifiers
    managed=set();all_types=type_ids(source);old_types=all_types-set(type_sets.profile().values())
    old_groups={name for name,value in type_sets.profile().items() if value in all_types}
    import metadata_object_xml
    managed.update(metadata_object_xml.reference_dependencies(source,layout,oid))
    if old_types or old_groups:
        reader=native_references.Catalog(request)
        storage=contexts.decode(request['storage'],'Source type dependencies require current version storage') if 'storage' in request else None
        managed.update(type_sets.dependencies(old_groups,reader,storage))
    if old_types:
        kinds=reference_kinds();matched=set()
        # A self reference has no separate repository dependency.
        own={s.val(source[1][slot]) for slot in layout['generated_slots']}
        matched.update(old_types & own)
        for identity in reader.targets.targets:
            kind=metadata_identifiers.class_labels().get(identity.class_id)
            if kind not in kinds or identity.object_id==oid or relations.get(identity.object_id)!=0:continue
            entry=reader.load(identity,storage,label='Source reference type')
            values=set(native_references.generated_ids(entry.body,identity,profiles.layout(kind,request['platform']))) & old_types
            if values:matched.update(values);managed.add(identity.object_id)
        if strict and matched!=old_types:raise ValueError('Source generated reference types lack verified repository dependencies')
    return managed


def reconcile(request,source,target,layout,relations,oid,xml):
    """Replace only proven structured dependencies; retain opaque relations."""
    managed=source_owners(request,source,layout,relations,oid)
    final=object_ids(xml,native_references.catalog(request))
    # A target may still use an owner through another structured property.
    atoms=set()
    def collect(node):
        if isinstance(node,list):
            for child in node:collect(child)
        else:atoms.add(s.val(node))
    collect(target)
    for key in managed:
        if relations.get(key)==0 and key not in final and key not in atoms:relations.pop(key)
    for key in final:
        if key!=oid:relations.setdefault(key,0)
    return relations
