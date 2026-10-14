"""Ownership traversal and live dependency closure for repository snapshots."""
import metadata_serializer as s


def closure(objects,root,children):
    if root not in objects:raise ValueError('Missing graph root')
    active=set();seen=set();order=[];owners={}
    def visit(oid,depth=0):
        if depth>128:raise ValueError('Object tree is too deep')
        if oid in active:raise ValueError('Cycle in object tree')
        if oid in seen:return
        if oid not in objects:raise ValueError('Missing child or related object: '+oid)
        active.add(oid);seen.add(oid);order.append(oid)
        for child,cls in children(objects[oid][0]):
            if child in owners:raise ValueError('Duplicate child ownership')
            owners[child]=oid
            if child not in objects or s.val(objects[child][0][2])!=cls or s.val(objects[child][0][3])!=oid:raise ValueError('Child class or parent mismatch')
            visit(child,depth+1)
        active.remove(oid)
    visit(root)
    index=0
    while index<len(order):
        oid=order[index];index+=1;m=objects[oid][0]
        # Absent relation UUIDs can be historical dependencies retained by 1C.
        for related in s.metadata_relations(m[14]):
            if related in objects:visit(related)
        parent=s.val(m[3])
        if parent!=s.ZERO:
            if parent not in objects or (oid,s.val(m[2])) not in children(objects[parent][0]):raise ValueError('Object is absent from its parent collection')
            visit(parent)
    return order
