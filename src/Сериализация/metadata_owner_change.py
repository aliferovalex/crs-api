"""Edit common properties and stored children using a version-bound XML baseline.

Common fields and verified form roles are patched independently. Unmapped owner
properties remain protected by the complete XML baseline.
"""
import metadata_context
import xml_namespaces
import copy
from xml.etree import ElementTree as E
import native_metadata as s
import metadata_identifiers as ids
import serialization_context as contexts
import native_collection_editor as collections
import packet_builder as packets
import metadata_owner_profiles as profiles
import metadata_structure


def canonical(node):
    text=node.text or ''
    if len(node) and not text.strip():text=''
    return (node.tag,tuple(sorted(node.attrib.items())),text,tuple(canonical(child) for child in node))


def retained_xml(root,kind,*,ignore_form_properties=False,ignore_common_properties=False):
    """Only stored child names are edited independently of owner properties.

    Inline children (attributes, dimensions, tabular sections, commands, ...)
    are part of the owner itself and must stay in this comparison.
    """
    result=copy.deepcopy(root);q='{'+xml_namespaces.MD+'}'
    stored={q+row['xml_name'] for row in metadata_structure.profile(kind)['collections'] if row['storage']=='stored_name'}
    children=result[0].find(q+'ChildObjects')
    if children is not None:
        for node in list(children):
            if node.tag in stored:children.remove(node)
        if not len(children) and not (children.text or '').strip():children.text=None
    if ignore_form_properties:
        import owned_form_properties
        names={q+name for name in owned_form_properties.profiles().get(kind,{}).get('properties',{})}
        props=result[0].find(q+'Properties')
        if props is not None:
            for node in list(props):
                if node.tag in names:props.remove(node)
    if ignore_common_properties:
        props=result[0].find(q+'Properties')
        if props is not None:
            name=props.findtext(q+'Name')
            internal=result[0].find(q+'InternalInfo')
            # Only derived owner-name segments are equivalent under rename.
            # Generated UUIDs, type prefixes and field suffixes remain compared.
            if name and internal is not None:
                for node in internal.findall('{'+xml_namespaces.READABLE+'}GeneratedType'):
                    value=node.get('name','');suffix='.'+name
                    if value.endswith(suffix):node.set('name',value[:-len(suffix)]+'.${ObjectName}')
            if name:
                xml_kind=metadata_structure.profile(kind)['xml_name'];prefix=xml_kind+'.'+name+'.'
                for node in result[0].iter('{'+xml_namespaces.READABLE+'}Field'):
                    value=node.text or ''
                    if value.startswith(prefix):node.text=xml_kind+'.${ObjectName}.'+value[len(prefix):]
            for node in list(props):
                if node.tag in {q+'Name',q+'Synonym',q+'Comment'}:props.remove(node)
    return canonical(result)


def content(request,*,reference_objects=None):
    kind=request['object_type'];oid=metadata_context.guid(request['object_id'])
    if kind not in profiles.owner_profiles():raise ValueError('Unsupported opaque metadata owner')
    before=request.get('before_xml')
    if before is None:raise ValueError('Unmapped owner properties require the original complete owner XML')
    for text in (before,request['object_xml']):
        if not isinstance(text,str) or len(text.encode('utf-8'))>s.MAX_BYTES or '<!DOCTYPE' in text.upper():raise ValueError('Invalid metadata owner XML')
    old=E.fromstring(before);new=E.fromstring(request['object_xml']);q='{'+xml_namespaces.MD+'}'
    for root in (old,new):
        if root.tag!=q+'MetaDataObject' or len(root)!=1 or root[0].tag!=q+profiles.owner_profiles()[kind]['owner_xml'] or root[0].attrib!={'uuid':oid}:raise ValueError('Metadata owner XML identity differs')
        if len(root[0].findall(q+'ChildObjects'))!=1:raise ValueError('Complete metadata owner requires ChildObjects')
    objects=metadata_context.context_objects(request['context']) if request.get('context') else {}
    import opaque_owner_references
    checked_old,checked_new=opaque_owner_references.equivalent_roots(old,new,kind,objects,reference_objects)
    if retained_xml(checked_old,kind,ignore_form_properties=True,ignore_common_properties=True)!=retained_xml(checked_new,kind,ignore_form_properties=True,ignore_common_properties=True):raise ValueError('Unmapped owner properties must remain unchanged')
    frame=contexts.read(request,oid);m=frame.metadata
    if s.val(m[2])!=ids.class_id(kind):raise ValueError('Metadata owner metadata class differs')
    contexts.original_version(request['original_version'],m)
    source=s.inflate(frame.data);body=s.Parser(source.decode('utf-8-sig')).documents()[0]
    common=profiles.owner_common(body,kind)
    opaque_owner_references.equivalent_roots(old,new,kind,objects,reference_objects,body=body)
    names=old[0].findall(q+'Properties/'+q+'Name')
    if len(names)!=1 or names[0].text!=s.val(m[9]) or s.val(common[2])!=s.val(m[9]):raise ValueError('Metadata owner XML name differs')
    removed=request.get('_removed_children',[])
    import automatic_deletion
    expected=automatic_deletion.missing(request['object_xml'],oid,objects,reference_objects=reference_objects)
    if set(expected)!={key for key in removed if key in objects and s.val(objects[key][0][3])==oid}:raise ValueError('Owner deletion plan differs')
    raw=collections.edit_raw(source,kind,m,objects,removed)
    import owned_form_properties
    raw,previous_roles,final_roles=owned_form_properties.patch(raw,kind,oid,old,new,objects,reference_objects if reference_objects is not None else objects)
    import metadata_common_xml
    raw,name=metadata_common_xml.patch(raw,profiles.owner_profiles()[kind]['owner_common_path'],old,new,oid,allow_rename=request.get('_allow_rename',False))
    m[9]=s.atom(name,True)
    refs=s.metadata_relations(m[14]);refs={key:flag for key,flag in refs.items() if not (key in removed and flag==1)}
    remaining={child for child,_ in metadata_context.children(m) if child not in removed}
    retired=set(previous_roles.values())-set(final_roles.values())-{s.ZERO}
    other=None
    if retired:
        other=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        for path in owned_form_properties.profiles().get(kind,{}).get('properties',{}).values():
            collections.at(other,path[:-1])[path[-1]]=s.atom(s.ZERO)
        for row in collections.inspect(body,kind,m,objects):
            value=collections.at(other,row['path']);value[:]=[value[0],s.atom(0)]
    def referenced(node,key):
        return any(referenced(child,key) for child in node) if isinstance(node,list) else s.val(node)==key
    for key in retired:
        if referenced(other,key):continue
        if key in remaining:refs[key]=1
        else:refs.pop(key,None)
    refs.update({key:0 for key in final_roles.values() if key!=s.ZERO})
    m[14]=[s.atom(len(refs))]+[s.atom(key) for key in refs]+[s.atom(flag) for flag in refs.values()]
    import inline_command_xml
    return frame,raw,inline_command_xml.preserve_owner_streams(frame.docs,oid,body,kind,request['platform'])


def serialize(request,native_content=False,*,reference_objects=None):
    frame,raw,ext=content(request,reference_objects=reference_objects)
    if native_content:
        from native_content import ObjectContent
        return ObjectContent(frame.docs,raw,[],ext)
    original=contexts.original_version(request['original_version'],frame.metadata)
    pairs=[(key,cls) for key,cls in metadata_context.children(frame.metadata) if key not in request.get('_removed_children',[])]
    return dict(request_xml=packets.pack_body_change(request,frame.docs,frame.saved,raw,original,pairs,externals=ext),external_owners=[])
