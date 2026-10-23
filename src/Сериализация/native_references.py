"""Final reference identities with compiled bodies or verified source records.

Compiled objects are never represented as repository snapshots or source versions.
"""
import base64
import uuid
from dataclasses import dataclass

import external_data
import metadata_context
import metadata_targets
import native_metadata as s
import serialization_context as contexts


def feature_ids(metadata):
    row=metadata[13]
    if not row or s.val(row[0])!=str(len(row)-1):raise ValueError('Invalid reference features')
    result=frozenset(str(uuid.UUID(s.val(value))) for value in row[1:])
    if len(result)!=len(row)-1:raise ValueError('Duplicate reference features')
    return result


@dataclass(frozen=True)
class Entry:
    identity: metadata_targets.Target
    body: bytes
    features: frozenset


@dataclass(frozen=True)
class FileEntry:
    identity: metadata_targets.Target
    body: bytes
    files: dict


class Catalog:
    def __init__(self,request,targets=None):
        self.request=request
        self.source=metadata_context.context_objects(request['context'])
        self.targets=metadata_targets.index(self.source) if targets is None else metadata_targets.index(targets)
        self.compiled={}
        self.allocations={}

    def declare(self,allocation):
        import metadata_object_xml as xml
        if not isinstance(allocation,xml.TypeAllocation):raise ValueError('Invalid native type declaration')
        identity=self.select(allocation.kind,allocation.name,label='Declared type')
        if identity.object_id!=allocation.object_id or identity.object_id in self.source or identity.object_id in self.allocations:raise ValueError('Duplicate or mismatched native type declaration')
        layout=xml.profiles.layout(allocation.kind,allocation.platform)
        values=allocation.generated
        if len(values)!=len(layout['generated_slots']) or len(set(values+(identity.object_id,)))!=len(values)+1 or s.ZERO in values:raise ValueError('Invalid declared generated UUIDs')
        for value in values:
            if str(uuid.UUID(value))!=value:raise ValueError('Invalid declared generated UUID')
        self.allocations[identity.object_id]=allocation

    def type_id(self,kind,name,category=None,storage=None):
        import metadata_object_xml as xml
        identity=self.select(kind,name,label='Referenced type')
        allocation=self.allocations.get(identity.object_id)
        layout=xml.profiles.layout(kind,self.request['platform'])
        if category is None:category=layout.get('reference_category','Ref')
        categories=layout.get('generated_categories',('Object','Ref','Selection','List','Manager'))
        if category not in categories or len(layout['generated_slots'])!=len(categories)*2:raise ValueError('Unsupported generated reference category')
        position=list(categories).index(category)*2
        if allocation is not None:return allocation.generated[position]
        entry=self.load(identity,storage,label='Reference type')
        return generated_ids(entry.body,entry.identity,layout)[position]

    def select(self,kind,name,label='Reference'):
        import metadata_identifiers as ids
        matches=self.targets.find({ids.class_id(kind)},name)
        if not matches:raise ValueError(label+' is missing from current context or final configuration: '+kind+'.'+name)
        if len(matches)!=1:raise ValueError('Ambiguous '+label.lower()+' metadata: '+kind+'.'+name)
        return matches[0]

    def register(self,oid,body,features):
        matches=[row for row in self.targets.targets if row.object_id==oid]
        if len(matches)!=1 or not isinstance(body,bytes) or len(body)>s.MAX_BYTES:raise ValueError('Invalid compiled reference body')
        if oid in self.allocations:
            import metadata_object_xml as xml
            allocation=self.allocations[oid]
            if tuple(generated_ids(body,matches[0],xml.profiles.layout(allocation.kind,allocation.platform)))!=allocation.generated:raise ValueError('Compiled generated UUIDs differ from declaration')
        self.compiled[oid]=Entry(matches[0],body,frozenset(features))

    def source_identity(self,identity):
        """Prove source identity separately from a validated final name."""
        m=self.source[identity.object_id][0]
        if (s.val(m[2]),s.val(m[3]),s.val(m[4]))!=(identity.class_id,identity.parent_id,identity.owner_id):raise ValueError('Final/source reference identity mismatch')
        name=s.val(m[9])
        if name!=identity.name and self.targets.renames.get(identity.object_id)!=(name,identity.name):raise ValueError('Final/source reference identity mismatch')
        return metadata_targets.Target(identity.object_id,identity.class_id,identity.parent_id,identity.owner_id,name,frozenset(metadata_context.children(m)))

    def load(self,identity,storage=None,label='Reference'):
        oid=identity.object_id
        if oid in self.compiled:return self.compiled[oid]
        if oid not in self.source:raise ValueError('Reference definition is not compiled: '+identity.name)
        m=self.source[oid][0]
        source_identity=self.source_identity(identity)
        if storage is not None:
            record=external_data.extract(storage,oid)
            if (record['class_id']!=s.val(m[2]) or record['parent_id']!=s.val(m[3]) or record['version_number']!=int(s.val(m[5]))
                    or record['original']!=uuid.UUID(s.val(m[7])).bytes_le.hex() or record['local']!=uuid.UUID(s.val(m[8])).bytes_le.hex()):
                raise ValueError(label+' version storage/context mismatch')
            raw=s.inflate(base64.b64decode(record['data'],validate=True))
        else:
            snapshots=self.request.get('reference_snapshots',self.request.get('snapshots',{}))
            if oid==self.request.get('object_id') and 'snapshot' in self.request:snapshots=dict(snapshots,**{oid:self.request['snapshot']})
            if not isinstance(snapshots,dict) or oid not in snapshots:raise ValueError('Referenced object snapshot is required: '+oid)
            frame=contexts.read(dict(self.request,snapshot=snapshots[oid]),oid,mismatch_error=label+' snapshot/context mismatch')
            if feature_ids(frame.saved[0])!=feature_ids(m):raise ValueError(label+' snapshot features mismatch')
            raw=s.inflate(frame.data)
        return Entry(source_identity,raw,feature_ids(m))

    def source_files(self,identities,storage,label='Reference files'):
        """Read source bodies and all streams once, even when targets are compiled."""
        identities=list(identities);records=external_data.extract_many(storage,{row.object_id for row in identities});result={}
        for identity in identities:
            oid=identity.object_id
            if oid not in self.source:raise ValueError(label+' requires an existing source object')
            m=self.source[oid][0];record=records[oid]
            source_identity=self.source_identity(identity)
            if (record['class_id'],record['parent_id'],record['version_number'],record['original'],record['local'])!=(s.val(m[2]),s.val(m[3]),int(s.val(m[5])),uuid.UUID(s.val(m[7])).bytes_le.hex(),uuid.UUID(s.val(m[8])).bytes_le.hex()):raise ValueError(label+' version storage/context mismatch')
            refs=m[11]
            if len(refs)!=1+2*int(s.val(refs[0])) or len(set(s.val(value) for value in refs[1::2]))!=int(s.val(refs[0])):raise ValueError('Invalid source external reference map')
            expected={s.val(refs[i]):uuid.UUID(s.val(refs[i+1])).bytes_le.hex()+'00000000' for i in range(1,len(refs),2)}
            if expected!={entry['name']:entry['version'] for entry in record['externals']}:raise ValueError(label+' external versions/context mismatch')
            files={entry['name']:s.inflate(base64.b64decode(entry['data'],validate=True)) for entry in record['externals']}
            result[oid]=FileEntry(source_identity,s.inflate(base64.b64decode(record['data'],validate=True)),files)
        return result


def generated_ids(raw,identity,layout):
    import metadata_object_xml as xml
    docs=s.Parser(raw.decode('utf-8-sig')).documents()
    if len(docs)!=1:raise ValueError('Unsupported reference type documents')
    body=docs[0];template=s.Parser(layout['template']).documents()[0]
    if not isinstance(body,list) or len(body)!=len(template) or not isinstance(body[1],list) or len(body[1])!=len(template[1]) or s.val(body[0])!=s.val(template[0]) or s.val(body[1][0])!=s.val(template[1][0]):raise ValueError('Unsupported reference type native layout')
    common=body
    for slot in xml.common_path(layout):common=common[slot]
    if s.val(common[1][2])!=identity.object_id or s.val(common[2])!=identity.name:raise ValueError('Reference type body/metadata identity mismatch')
    result=[str(uuid.UUID(s.val(body[1][slot]))) for slot in layout['generated_slots']]
    if len(set(result+[identity.object_id]))!=len(result)+1 or s.ZERO in result:raise ValueError('Invalid generated reference type UUIDs')
    return result


def catalog(request):
    result=request.get('_native_references')
    if result is None:return Catalog(request)
    if not isinstance(result,Catalog):raise ValueError('Invalid internal native reference catalog')
    return result
