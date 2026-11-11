"""Repository links read from compiled identities, never application writers."""
from xml.etree import ElementTree as E
import compiled_graph
import metadata_type_references
import native_metadata as s


def generated_owners(record):
    result={}
    def visit(node,owner):
        if 'uuid' in node.attrib:owner=compiled_graph.identifier(node.get('uuid'))
        if node.tag==compiled_graph.XR+'GeneratedType':
            for key in ('TypeId','ValueId'):
                value=node.findtext(compiled_graph.XR+key)
                if value:result.setdefault(owner,set()).add(compiled_graph.identifier(value))
        for child in node:visit(child,owner)
    visit(record['node'],record['id']);return result


def validate_surviving_types(source,target):
    old=generated_owners(source);new=generated_owners(target)
    surviving={target['id'],*compiled_graph.features(target)}
    for owner in old.keys() & surviving:
        if old[owner]!=new.get(owner,set()):raise ValueError('Compiler changed generated identity of a surviving metadata object')


def identity_owner(index,value):
    if value in index.inventory:return value
    owner=index.owner_for_generated(value)
    if owner is not None:return owner
    oid=index.feature_owners.get(value)
    if oid is not None:
        index.facts(oid)
        return value if index.inventory[oid]['kind']=='Configuration' else oid
    return None


def validate_reference_changes(source, target, before, after, object_id):
    """Allow changed reference counts only for identities proven on each side.

    Callers remove stored collection entries first. The owner's own UUIDs and
    unknown native constants remain protected; application slots are not read
    or written here. Full compiler round-trip verification remains mandatory.
    """
    for value in before.keys() | after.keys():
        removed = (value in source.inventory or value in source.owners or value in source.feature_owners) and not (
            value in target.inventory or value in target.owners or value in target.feature_owners)
        if before.get(value, 0) == after.get(value, 0) and not removed:
            continue
        for index, counts in ((source, before), (target, after)):
            if not counts.get(value, 0):
                continue
            owner = identity_owner(index, value)
            if (owner is None or owner == object_id or owner not in index.inventory
                    or index.feature_owners.get(value) == object_id):
                raise ValueError('Compiler changed undeclared configuration references: ' + value)
            index.facts(owner)


def references(index,record,body,image,xml):
    """Known native references plus XML types; opaque links are not guessed."""
    oid=record['id'];facts=index.facts(oid);nodes=s.Parser(body.decode('utf-8-sig')).documents()
    values=compiled_graph.atoms(nodes)-{oid,*facts.features,*facts.generated}
    kind=record['kind'];streams={name:raw for name,raw in image.items() if name.startswith(oid+'.')}
    if kind in ('Role','Template','CommonTemplate') and streams:
        import external_dependencies
        values.update(external_dependencies.stream_references(kind,oid,body,streams))
    result={}
    for value in values:
        owner=identity_owner(index,value)
        if owner is not None and owner!=oid:result[owner]=0
    declared=metadata_type_references.required(xml,index)
    if not set(index.resolve_required(declared).values())<=metadata_type_references.type_ids(nodes):
        raise ValueError('Compiled metadata lacks declared reference type UUIDs')
    for owner in index.object_ids_required(declared):
        if owner!=oid:result.setdefault(owner,0)
    for children in facts.children.values():
        for child in children:result[child]=1
    if facts.parent_id!=s.ZERO:result[facts.parent_id]=1
    return result


def reconcile(request,change,body,image,previous=None,source_body=None,source_image=None):
    index=request['_compiled_types'];oid=change['object_id'];record=index.inventory[oid]
    final=references(index,record,body,image,change['object_xml'])
    result=dict(previous or {})
    if source_body is not None:
        source=request['_source_types'];old=source.inventory[oid]
        validate_surviving_types(old,record)
        managed=references(source,old,source_body,source_image,old.get('xml',E.tostring(old['node'],encoding='unicode')))
        for owner in managed:
            if owner not in final and result.get(owner) in (0,1):result.pop(owner)
    for owner,flag in final.items():result.setdefault(owner,flag)
    if record['parent_id']!=s.ZERO:result[record['parent_id']]=1
    for children in index.facts(oid).children.values():
        for child in children:result[child]=1
    return [s.atom(len(result))]+[s.atom(owner) for owner in result]+[s.atom(flag) for flag in result.values()]
