"""Verified XML reference aliases retain the source UUID in opaque owners."""
import copy
import metadata_identifiers as ids
import metadata_targets as targets
import native_collection_editor as collections
import native_metadata as s
import xml_namespaces

Q='{'+xml_namespaces.MD+'}'
PROFILES={
    'BusinessProcess':{'Task':('Task',(1,25))},
    'CalculationRegister':{'ChartOfCalculationTypes':('ChartOfCalculationTypes',(1,22))},
}


def equivalent_roots(before,after,kind,objects,reference_objects=None,*,body=None):
    """Resolve changed known properties against source and authorized final names.

    This permits aliases of the same UUID only. It does not authorize changing
    reference targets or ignoring arbitrary text properties. Actual native atoms
    are checked again when the source body is available to the compiler.
    """
    rules=PROFILES.get(kind,{})
    if not rules:return before,after
    old,new=copy.deepcopy(before),copy.deepcopy(after);source=final=None
    for prop,(target_kind,path) in rules.items():
        a=old[0].findall(Q+'Properties/'+Q+prop);b=new[0].findall(Q+'Properties/'+Q+prop)
        if len(a)>1 or len(b)>1:raise ValueError('Duplicate opaque reference property: '+prop)
        if not a or not b:continue
        a,b=a[0],b[0]
        if a.text==b.text and a.attrib==b.attrib and not len(a) and not len(b):continue
        if a.attrib or b.attrib or len(a) or len(b):raise ValueError('Invalid opaque reference property: '+prop)
        if source is None:
            source=targets.index(objects);final=targets.index(reference_objects if reference_objects is not None else objects)
        def resolve(node,index):
            value=node.text or '';prefix=target_kind+'.'
            if not value.startswith(prefix) or not value[len(prefix):] or '.' in value[len(prefix):]:raise ValueError('Invalid opaque reference: '+prop)
            matches=index.find({ids.class_id(target_kind)},value[len(prefix):])
            if len(matches)!=1:raise ValueError('Missing or ambiguous opaque reference: '+prop)
            row=matches[0]
            roots=[parent for parent in index.targets if parent.object_id==row.parent_id and parent.class_id==ids.class_id('Configuration')]
            if len(roots)!=1 or row.owner_id!=s.ZERO:raise ValueError('Invalid opaque reference ownership: '+prop)
            return row
        previous,current=resolve(a,source),resolve(b,final)
        if (previous.object_id,previous.class_id,previous.parent_id,previous.owner_id)!=(current.object_id,current.class_id,current.parent_id,current.owner_id):
            raise ValueError('Changing opaque reference UUID is unsupported: '+prop)
        if previous.name!=current.name and final.renames.get(previous.object_id)!=(previous.name,current.name):
            raise ValueError('Opaque reference rename is not authorized: '+prop)
        if body is not None:
            atom=collections.at(body,path)
            if isinstance(atom,list) or atom.quoted or s.val(atom)!=previous.object_id:raise ValueError('Source opaque reference differs from native snapshot: '+prop)
        a.text=b.text=previous.object_id
    return old,new
