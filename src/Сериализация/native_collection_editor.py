"""Edit mapped stored child collections while retaining opaque owner contents.

Candidate offsets never authorize writes. Each row is checked against the actual
snapshot, child descriptors, class UUID, order and positions before any mutation.
"""
import metadata_context
import xml_namespaces
import copy
from xml.etree import ElementTree as E
import native_metadata as s
import metadata_structure as structure

Q='{'+xml_namespaces.MD+'}'


def at(body,path):
    try:
        node=body
        for index in path:
            if not isinstance(index,int) or isinstance(index,bool) or index<0:raise ValueError('Invalid native collection path')
            node=node[index]
        return node
    except (IndexError,TypeError):raise ValueError('Native collection path differs from snapshot') from None


def rules(kind):
    return [v for v in structure.profile(kind)['collections'] if v['storage']=='stored_name']


def creation_row(body,cls):
    """Find a verified class row in a newly compiled owner's native tree."""
    rows=[]
    def walk(node):
        if isinstance(node,list):
            if node and isinstance(node[0],s.Atom) and s.val(node[0])==cls:rows.append(node)
            for child in node:walk(child)
    walk(body)
    if len(rows)!=1:raise ValueError('New owner collection is missing or ambiguous')
    row=rows[0]
    if len(row)<2 or s.val(row[1])!=str(len(row)-2) or len({s.val(key) for key in row[2:]})!=len(row)-2:raise ValueError('Invalid new owner collection')
    return row


def inspect(body,kind,metadata,objects):
    profile=structure.profile(kind)
    if profile['class_id'] and s.val(metadata[2])!=profile['class_id']:raise ValueError('Owner metadata class differs from map')
    if profile.get('native_identity_path') is None:raise ValueError('Unmapped native owner identity')
    owner=metadata_context.guid(s.val(metadata[1]))
    if metadata_context.guid(s.val(at(body,profile['native_identity_path'])))!=owner:raise ValueError('Native owner UUID differs from metadata')
    pairs=metadata_context.children(metadata);result=[];checked=[]
    for rule in rules(kind):
        native=rule['native'];cls=rule['item_class_id']
        expected=[oid for oid,child_class in pairs if child_class==cls]
        if native['status'] not in ('verified_profile','snapshot_collection') or native['format']!='class_uuid,count,object_uuids':
            if expected:raise ValueError('Unmapped stored collection: '+kind+'.'+rule['xml_name'])
            continue
        if not cls:
            if expected:raise ValueError('Unmapped stored collection class UUID')
            continue
        path=native['path']
        if path is None:
            paths=[]
            def locate(node,prefix=()):
                if not isinstance(node,list):return
                if len(node)>=2 and not isinstance(node[0],list) and s.val(node[0]).lower()==cls:paths.append(list(prefix))
                for index,child in enumerate(node):locate(child,prefix+(index,))
            locate(body)
            if not paths and not expected:continue
            if len(paths)!=1:raise ValueError('Missing or ambiguous native collection: '+rule['xml_name'])
            path=paths[0]
        row=at(body,path)
        if (not isinstance(row,list) or len(row)<2 or isinstance(row[0],list) or isinstance(row[1],list)
                or s.val(row[0]).lower()!=cls or row[0].quoted or row[1].quoted or s.val(row[1])!=str(len(row)-2)
                or any(isinstance(key,list) or key.quoted for key in row[2:])):raise ValueError('Invalid native stored collection')
        keys=[metadata_context.guid(s.val(key)) for key in row[2:]]
        if len(keys)!=len(set(keys)) or set(keys)!=set(expected):raise ValueError('Body/context child collection mismatch')
        positions=[]
        for key in keys:
            if key not in objects:raise ValueError('Missing native child descriptor')
            m=objects[key][0]
            if s.val(m[2])!=cls or s.val(m[3])!=owner or s.val(m[4])!=s.ZERO or not s.val(m[10]).isdecimal():raise ValueError('Native child class, parent or position mismatch')
            positions.append(int(s.val(m[10])));checked.append((key,cls))
        if positions!=sorted(set(positions)):raise ValueError('Native child positions are duplicated or out of order')
        result.append(dict(rule=rule,path=path,ids=keys))
    if set(checked)!=set(pairs):raise ValueError('Unmapped separately stored child collection')
    return result


def edit(body,kind,metadata,objects,removed):
    removed={metadata_context.guid(key) for key in removed}
    rows=inspect(body,kind,metadata,objects);target=copy.deepcopy(body)
    for entry in rows:
        row=at(target,entry['path']);keys=[key for key in row[2:] if metadata_context.guid(s.val(key)) not in removed]
        row[:]=[row[0],s.atom(len(keys))]+keys
    return target


def restore(target,source,kind,metadata,objects):
    """Restore current stored rows after conversion of the owner's properties."""
    target=copy.deepcopy(target)
    for entry in inspect(source,kind,metadata,objects):
        path=entry['path'];row=at(target,path)
        if not isinstance(row,list) or len(row)<2 or s.val(row[0])!=entry['rule']['item_class_id']:raise ValueError('Converted owner collection differs from map')
        at(target,path[:-1])[path[-1]]=copy.deepcopy(at(source,path))
    return target


def replace(body,source,kind,metadata,objects,desired,final_objects):
    """Replace mapped rows with the final children after validating the source."""
    target=copy.deepcopy(body);rows=inspect(source,kind,metadata,objects);covered=set()
    for entry in rows:
        cls=entry['rule']['item_class_id'];keys=[oid for oid,child_cls in desired if child_cls==cls]
        row=at(target,entry['path'])
        if not isinstance(row,list) or s.val(row[0])!=cls:raise ValueError('Final native collection differs from map')
        positions=[]
        for oid in keys:
            m=final_objects[oid][0]
            if s.val(m[2])!=cls or s.val(m[3])!=s.val(metadata[1]) or s.val(m[4])!=s.ZERO:raise ValueError('Final child descriptor differs from its collection')
            positions.append(int(s.val(m[10])));covered.add((oid,cls))
        if positions!=sorted(set(positions)):raise ValueError('Final child positions are duplicated or out of order')
        row[:]=[row[0],s.atom(len(keys))]+[s.atom(oid) for oid in keys]
    if covered!=set(desired):raise ValueError('Final child collection has no verified native row')
    return target


def strip_xml(text,kind):
    """Keep inline XML; stored collections are changed only by this editor."""
    if not isinstance(text,str) or len(text.encode('utf-8'))>s.MAX_BYTES or '<!DOCTYPE' in text.upper():raise ValueError('Invalid native editor XML')
    root=E.fromstring(text)
    if root.tag!=Q+'MetaDataObject' or len(root)!=1 or root[0].tag!=Q+structure.profile(kind)['xml_name']:raise ValueError('Unexpected native editor XML owner')
    children=root[0].find(Q+'ChildObjects');tags={Q+v['xml_name'] for v in rules(kind)}
    if children is not None:
        for child in list(children):
            if child.tag in tags:children.remove(child)
    import xml_namespaces
    return xml_namespaces.render(root,text)


def edit_raw(raw,kind,metadata,objects,removed):
    """Splice only changed rows, preserving every byte outside those spans."""
    text=raw.decode('utf-8-sig');docs=s.Parser(text).documents()
    if len(docs)!=1:raise ValueError('Expected one native owner body')
    rows=inspect(docs[0],kind,metadata,objects);removed={metadata_context.guid(key) for key in removed};patches=[]
    for entry in rows:
        row=at(docs[0],entry['path'])
        if not set(entry['ids'])&removed:continue
        start,end=row.start,row.end
        if start<0 or text[start]!='{' or text[end-1]!='}':raise ValueError('Unsupported native collection span')
        keys=[key for key in row[2:] if metadata_context.guid(s.val(key)) not in removed]
        patches.append((start,end,s.render([row[0],s.atom(len(keys))]+keys)))
    for start,end,value in sorted(patches,reverse=True):text=text[:start]+value+text[end:]
    return (b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'')+text.encode('utf-8')
