"""Resolve form reference types through version-checked native metadata bodies."""
import metadata_context
import native_metadata as s
import metadata_identifiers as ids
import metadata_type_references as references
import metadata_type_sets as type_sets
import xml_namespaces

Q='{http://v8.1c.ru/8.3/xcf/logform}'
CORE='{http://v8.1c.ru/8.1/data/core}'


def required(xml,index=None):
    if xml is None:return set()
    if not isinstance(xml,str) or len(xml.encode('utf-8'))>s.MAX_BYTES or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():raise ValueError('Invalid reference type XML')
    root,scopes=xml_namespaces.parse(xml)
    # Only the main attribute's own type is supplied by its final owner.
    # Columns below it, parameters and every other declaration still have
    # independent reference dependencies, even when no control uses them.
    main_types=set()
    for attr in root.findall(Q+'Attributes/'+Q+'Attribute'):
        if attr.findtext(Q+'MainAttribute')!='true':continue
        node=attr.find(Q+'Type')
        if node is not None:main_types.update(node.iter())
    return references.required_nodes((node for node in root.iter() if node not in main_types),index,scopes)


def reference_name(value):
    return references.reference_name(value)


def objects_for_xml(xml,request):
    index=request.get('_compiled_types')
    refs=required(xml,index)
    if not refs:return refs,{}
    if index is not None:
        objects=metadata_context.context_objects(request['context'])
        wanted={index.reference(ref)[1] for ref in refs}
        wanted={index.feature_owners.get(oid,oid) for oid in wanted}
        if not wanted<=objects.keys():raise ValueError('Referenced type is missing from current context')
        return refs,{oid:(oid,objects[oid][0]) for oid in wanted}
    wanted={reference_name(ref) for ref in refs if ref not in type_sets.profile()};selected={}
    objects=metadata_context.context_objects(request['context'])
    if refs & type_sets.profile().keys():
        roots=[docs[0] for docs in objects.values() if s.val(docs[0][2])==ids.class_id('Configuration') and s.val(docs[0][3])==s.ZERO]
        if len(roots)!=1:raise ValueError('Form type sets require one Configuration root')
        wanted.add(('Configuration',s.val(roots[0][9])))
    for oid,docs in objects.items():
        m=docs[0];kind=ids.class_labels().get(s.val(m[2]));key=(kind,s.val(m[9]))
        if key in wanted:
            if key in selected:raise ValueError('Ambiguous form reference type in context')
            selected[key]=(oid,m)
    if set(selected)!=wanted:raise ValueError('Referenced type is missing from current context')
    return refs,selected


def resolve(xml,request,storage=None):
    return references.resolve_required(required(xml,request.get('_compiled_types')),request,storage)


def dependencies(xml,reader,storage=None):
    return references.required_object_ids(required(xml,reader.request.get('_compiled_types')),reader,storage)
