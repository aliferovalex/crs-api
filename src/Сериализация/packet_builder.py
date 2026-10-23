"""Shared native commit assembly; XML converters supply object bodies.

Record order, graph order and external actions are protocol data, not inferred
from a metadata class. Full repository-version reading has a separate validator.
"""
import base64
import copy
import hashlib
import struct
import uuid
import zlib
from dataclasses import dataclass
import xml.etree.ElementTree as E
import native_metadata as s
import xml_namespaces


def content_version(raw, identifier=None):
    # Experimental client version, retained from the existing serializers.
    return (identifier or uuid.uuid4()).bytes_le + struct.pack('<I', zlib.crc32(raw))


def external_version():
    return uuid.uuid4().bytes_le + bytes(4)


def preserve_external_versions(docs,oid,owned=()):
    """Keep server streams by version; no payload is supplied for action zero."""
    refs=docs[0][11];count=int(s.val(refs[0]));cache=docs[2]
    if count<0 or len(refs)!=1+count*2 or len({s.val(n) for n in refs[1::2]})!=count:
        raise ValueError('Unsupported external object map')
    if any(not s.val(n).startswith(oid+'.') and s.val(n) not in owned for n in refs[1::2]):
        raise ValueError('Unsupported external object map')
    if s.render(cache)!='{0}' and (len(cache)!=count+1 or s.val(cache[0])!=str(count)
            or any(len(row)!=3 or s.val(row[0])!=s.val(refs[1+i*2]) or s.val(row[1])!=s.val(refs[2+i*2]) or s.val(row[2])!='1' for i,row in enumerate(cache[1:]))):
        raise ValueError('Unsupported external context')
    result=[]
    for index in range(count):
        slot=2+index*2;version=uuid.UUID(s.val(refs[slot])).bytes_le+bytes(4)
        refs[slot]=s.atom(base64.b64encode(version).decode())
        result.append(dict(name=s.val(refs[slot-1]),version=version.hex(),action=0))
    docs[2]=[s.atom(0)]
    return result


def commit_metadata(metadata, original, local):
    a=s.atom
    metadata[0],metadata[5],metadata[6]=a(6),a(4294967295),a(0)
    metadata[7],metadata[8]=a(base64.b64encode(original).decode()),a(base64.b64encode(local).decode())


def descriptor(metadata):
    m=metadata
    return [m[1],m[2],m[3],m[9],m[10],m[5],m[6],m[3],m[4],m[7],m[8],s.atom(0)]


def description(metadata, original, local):
    m=metadata
    return dict(id=s.val(m[1]),class_id=s.val(m[2]),name=s.val(m[9]),pos=int(s.val(m[10])),
                parent_id=s.val(m[3]),owner_id=s.val(m[4]),original=original.hex(),local=local.hex())


@dataclass
class ObjectRecord:
    object_id: str
    metadata: bytes
    body: bytes
    externals: tuple = ()  # Ordered (name, compressed payload) pairs.


def assemble(graph, objects):
    """Build one commit, preserving caller-supplied object and stream order."""
    objects=list(objects);seen=set();records=[];a=s.atom;manifest=[a(0),a(len(objects))]
    if len(graph)!=15 or not objects:raise ValueError('Invalid commit graph or empty object set')
    for obj in objects:
        oid=str(uuid.UUID(obj.object_id))
        if oid in seen:raise ValueError('Duplicate commit object')
        seen.add(oid);records.extend([obj.metadata,obj.body])
        manifest.extend([a(oid),a(hashlib.sha1(obj.metadata).hexdigest(),True),a(hashlib.sha1(obj.body).hexdigest(),True),a(len(obj.externals))])
        names=set()
        for name,data in obj.externals:
            if name in names:raise ValueError('Duplicate external stream')
            names.add(name);records.append(data)
            manifest.extend([a(name,True),a(hashlib.sha1(data).hexdigest(),True)])
    storage=s.storage(records,s.text_bytes([manifest]));s.validate_storage(storage)
    return s.SERIALIZER+s.compress(s.record(s.text_bytes([graph]))+bytes(4)+s.record(storage))


def child_map(pairs):
    pairs=list(pairs);result=[s.atom(len(pairs))]
    for oid,cls in pairs:result.extend([s.atom(oid),s.atom(cls)])
    return result


def pack_body_change(request,docs,saved,raw,original,pairs,descriptor_order=None,externals=None):
    """Pack a verified whole-body replacement; callers supply class-specific maps."""
    m=docs[0];oid=s.val(m[1]);version=content_version(raw);source=bytes.fromhex(original)
    commit_metadata(m,source,version)
    m[15:17]=copy.deepcopy(saved[0][15:17]);docs[1]=copy.deepcopy(saved[1])
    graph=change_graph(m,child_map(pairs),externals=m[11] if externals is not None else None)
    payload=assemble(graph,[ObjectRecord(oid,s.text_bytes(docs),s.compress(raw))])
    return request_xml(request,payload,{oid:docs},{oid:source},{oid:version},externals={oid:externals} if externals is not None else None,descriptor_order=descriptor_order)


def change_graph(metadata, children, features=None, externals=None):
    a=s.atom;m=metadata;oid=s.val(m[1])
    features=m[13] if features is None else features
    externals=[a(0)] if externals is None else externals
    return [[a(1),a(oid),descriptor(m)],[a(1),[a(oid)]+copy.deepcopy(features)],
        [a(1),s.graph_relations(oid,m[14])],[a(1),a(oid),m[3]],
        [a(1),a(oid),a(1)],[a(1),a(oid),children],[a(0)],
        [a(1),a(oid),externals],[a(1),a(oid),a(1)],[a(1),a(oid),a(1)],
        a(0),[a(0)],a(0),[a(0)],[a(1),[a(0)]]]


def owned_object_creation_graph(objects, parent, new, pairs):
    """Shared graph for a new form or template and its unchanged owner siblings."""
    a=s.atom;m=objects[parent][0];fm=objects[new][0];desc={oid:descriptor(d[0]) for oid,d in objects.items()}
    return [[a(2),a(parent),desc[parent],a(new),desc[new]],[a(1),[a(parent)]+copy.deepcopy(m[13])],
        [a(2),s.graph_relations(new,fm[14]),s.graph_relations(parent,m[14])],
        [a(2),a(parent),m[3],a(new),a(parent)],[a(2),a(parent),a(1),a(new),a(1)],
        [a(1),a(parent),child_map(pairs)],[a(1),a(new),[a(1),a(new),desc[new]]],
        [a(2),a(new),fm[11],a(parent),m[11]],[a(2),a(parent),a(1),a(new),a(1)],
        [a(2),a(parent),a(1),a(new),a(1)],a(0),[a(0)],a(0),[a(0)],[a(1),[a(0)]]]


def top_level_creation_graph(objects, parent, new, order, children):
    a=s.atom;desc={oid:descriptor(objects[oid][0]) for oid in order}
    graph=[[a(2),a(parent),desc[parent],a(new),desc[new]],
        [a(len(order)-1)]+[[a(oid)]+objects[oid][0][13] for oid in order if oid!=new],
        [a(len(order))]+[s.graph_relations(oid,objects[oid][0][14]) for oid in [parent,new]+[v for v in order if v not in (parent,new)]],
        [a(2),a(parent),a(s.ZERO),a(new),a(parent)],
        [a(len(order))],[a(len(order)-1)],
        [a(2),a(new),[a(1),a(new),desc[new]],a(parent),[a(len(order))]],
        [a(len(order))],[a(2),a(parent),a(1),a(new),a(1)],
        [a(1),a(parent),a(1)],a(0),[a(0)],a(0),[a(0)],[a(1),[a(0)]]]
    for oid in [parent,new]+[v for v in order if v not in (parent,new)]:graph[4].extend([a(oid),a(1)])
    for oid in [parent]+[v for v in order if v not in (parent,new)]:graph[5].extend([a(oid),child_map(sorted(children(objects[oid][0])))])
    for oid in [parent]+[v for v in order if v not in (parent,new)]+[new]:graph[6][-1].extend([a(oid),desc[oid]])
    for oid in order:graph[7].extend([a(oid),objects[oid][0][11]])
    features=objects[new][0][13]
    if s.val(features[0])!='0':
        graph[1][0]=a(len(order));graph[1].append([a(new)]+copy.deepcopy(features))
    return graph


def subtree_creation_graph(objects, parent, new_ids, order, children,changed_ids=()):
    """Register a newly created object tree and its existing Configuration parent."""
    a=s.atom;touched=[parent]+list(new_ids)+list(changed_ids);desc={oid:descriptor(objects[oid][0]) for oid in order}
    if len(set(touched))!=len(touched):raise ValueError('Duplicate changed/new object')
    graph=[[a(len(touched))],[a(len(order))],[a(len(order))],[a(len(touched))],
        [a(len(order))],[a(0)],[a(len(touched))],[a(len(order))],
        [a(len(touched))],[a(len(touched))],a(0),[a(0)],a(0),[a(0)],[a(1),[a(0)]]]
    for oid in touched:
        graph[0].extend([a(oid),desc[oid]]);graph[3].extend([a(oid),objects[oid][0][3]])
        for section in (8,9):graph[section].extend([a(oid),a(1)])
        descendants=[]
        def collect(key):
            if key in descendants:raise ValueError('Cycle in creation subtree')
            descendants.append(key)
            for child,cls in children(objects[key][0]):collect(child)
        collect(oid);row=[a(len(descendants))]
        for child in descendants:row.extend([a(child),desc[child]])
        graph[6].extend([a(oid),row])
    for oid in order:
        m=objects[oid][0];graph[1].append([a(oid)]+copy.deepcopy(m[13]))
        graph[2].append(s.graph_relations(oid,m[14]));graph[4].extend([a(oid),a(1)])
        graph[7].extend([a(oid),m[11]])
        if oid not in new_ids or children(m):
            graph[5].extend([a(oid),child_map(children(m))]);graph[5][0]=a(int(s.val(graph[5][0]))+1)
    return graph


def deletion_graph(objects, kept, parent, removed, pairs, old_relations):
    removed={removed} if isinstance(removed,str) else set(removed)
    a=s.atom;m=kept[parent][0];descriptors=[a(len(kept))];parents=[a(len(kept))];flags=[a(len(kept))];active=[a(len(objects))]
    for oid,d in kept.items():
        descriptors.extend([a(oid),descriptor(d[0])]);parents.extend([a(oid),d[0][3]]);flags.extend([a(oid),a(1)])
    for oid in objects:active.extend([a(oid),a(0 if oid in removed else 1)])
    return [descriptors,[a(1),[a(parent)]+copy.deepcopy(m[13])],[a(0)],parents,active,
        [a(1),a(parent),child_map((oid,cls) for oid,cls in pairs if oid not in removed)],
        [a(0)],[a(1),a(parent),m[11]],flags,copy.deepcopy(flags),
        a(1),[a(len(old_relations))]+old_relations,a(0),[a(0)],[a(1),[a(0)]]]


def request_xml(request, payload, objects, originals, versions, externals=None, code='', features=None, descriptor_order=None):
    """Shared unauthenticated commit envelope; OneScript adds authentication."""
    E.register_namespace('crs',s.NS)
    call=E.Element('{%s}call'%s.NS,alias=request['repository'],name='DevDepot_commitObjects',version=request['platform'])
    def field(parent,key,value=None,text=None):
        node=E.SubElement(parent,'{%s}%s'%(s.NS,key));node.text=text
        if value is not None:node.set('value',str(value))
        return node
    p=field(call,'params');field(p,'clientVerID',str(uuid.UUID(request['repository_version'])));field(p,'data',text=base64.b64encode(payload).decode())
    ordering=descriptor_order or [('name',9),('pos',10),('verNum',None),('selfVerNum',None),('parentID',3),('ownerID',4)]
    for section in ('requested','changes'):
        container=field(p,section)
        for oid,docs in objects.items():
            m=docs[0];entry=field(container,'value');field(entry,'first',oid);second=field(entry,'second')
            detail=field(second,'_super') if section=='changes' else second
            supernode=field(detail,'_super');field(supernode,'id',oid);field(supernode,'classID',s.val(m[2]))
            for key,index in ordering:field(detail,key,s.val(m[index]) if index is not None else (-1 if key=='verNum' else 0))
            version=field(detail,'version');field(version,'original',originals[oid].hex());field(version,'local',versions[oid].hex());field(detail,'removed','false')
            if section=='changes':
                ext=field(second,'externals')
                for item in (externals or {}).get(oid,[]):
                    entry=field(ext,'value');field(entry,'first',item['name']);detail=field(entry,'second');supernode=field(detail,'_super')
                    field(supernode,'name',item['name']);field(supernode,'verID',item['version']);field(detail,'action',item['action'])
    field(p,'objectsToRemove');field(p,'code',code);field(p,'comment',text='');feature_node=field(p,'features')
    for oid,values in (features or {}).items():
        node=field(feature_node,'value');field(node,'first',oid);values_node=field(node,'second')
        for value in values:field(values_node,'value',value)
    return xml_namespaces.serialize(call)


def pack_external_change(content, original):
    """Shared single-object commit with one replaced external stream."""
    docs, raw, streams, externals = content
    m = docs[0];oid = s.val(m[1]);stream = externals[0]
    local = content_version(raw)
    a = s.atom
    commit_metadata(m, bytes.fromhex(original), local)
    meta = s.text_bytes(docs)
    graph = change_graph(m, [a(0)], features=[a(0)], externals=m[11])
    payload = assemble(graph, [ObjectRecord(oid, meta, s.compress(raw), tuple(streams))])
    return dict(data=base64.b64encode(payload).decode(), object_id=oid,
        class_id=s.val(m[2]), original=original, local=local.hex(),
        external_name=stream['name'], external_version=stream['version'])
