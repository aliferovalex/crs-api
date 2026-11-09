"""Read native object identity paths and structured dependencies."""
import xml_namespaces
import native_metadata as s

Q='{'+xml_namespaces.MD+'}'


def at(node,path):
    for slot in path:node=node[slot]
    return node


def common_path(layout):
    return layout.get('common_path',[1,layout.get('common_slot',9)]+([] if layout.get('common_direct') else [1]))


def stored_collections(body,kind,extra_classes=()):
    """Locate schema-declared stored child collections by their class UUID."""
    import uuid,metadata_structure
    classes={row['item_class_id'] for row in metadata_structure.profile(kind)['collections'] if row['storage']=='stored_name' and row.get('item_class_id')}
    classes.update(extra_classes)
    result={};seen=set()
    def walk(node):
        if not isinstance(node,list):return
        if node and isinstance(node[0],s.Atom) and s.val(node[0]) in classes:
            cls=s.val(node[0])
            if cls in result or len(node)<2 or not isinstance(node[1],s.Atom) or s.val(node[1])!=str(len(node)-2):raise ValueError('Invalid native stored child collection')
            values=[]
            for child in node[2:]:
                if not isinstance(child,s.Atom):raise ValueError('Invalid stored child UUID')
                oid=str(uuid.UUID(s.val(child)))
                if oid==s.ZERO or oid in seen:raise ValueError('Duplicate/zero stored child UUID')
                seen.add(oid);values.append(oid)
            result[cls]=values;return
        for child in node:walk(child)
    walk(body);return result


def reference_dependencies(source,layout,oid):
    """Mapped reference values and lists share one native dependency policy."""
    result={}
    for category in ('reference_values','reference_lists'):
        for rule in layout.get(category,{}).values():
            flag=rule.get('relation_flag',0)
            if flag is None:continue
            row=at(source,rule['path'])
            values=([s.val(at(item,rule['id_path'])) for item in row[2:]] if category=='reference_lists' else [s.val(row)])
            for key in values:
                if key!=s.ZERO and not (rule.get('exclude_self_dependency') and key==oid):result[key]=flag
    return result
