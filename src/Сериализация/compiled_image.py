"""Classify the complete native CF difference independently of XML properties."""
from dataclasses import dataclass
import native_metadata as s
import native_streams

SERVICE_RECORDS=frozenset(('root','version','versions'))


@dataclass(frozen=True)
class ObjectDelta:
    object_id: str
    operation: str
    body_changed: bool
    added_streams: tuple
    changed_streams: tuple
    removed_streams: tuple


class Delta:
    def __init__(self,before,after,source_ids,target_ids,objects):
        for name in ('root','version'):
            if before.get(name)!=after.get(name):raise ValueError('Compiler changed CF identity/format service record: '+name)
        source_ids=set(source_ids);target_ids=set(target_ids)
        owners={oid:oid for oid in source_ids|target_ids}
        for oid,docs in objects.items():
            for identity in native_streams.identities(docs[0]):
                if identity in owners and owners[identity]!=oid:raise ValueError('Ambiguous native feature ownership: '+identity)
                owners[identity]=oid
            for name in docs[0][11][1::2]:
                name=s.val(name)
                if name in owners and owners[name]!=oid:raise ValueError('Ambiguous native stream ownership: '+name)
                owners[name]=oid
        self.streams={oid:set() for oid in source_ids|target_ids};self.objects={};self.records={}
        for name in before.keys()|after.keys():
            if name in SERVICE_RECORDS:continue
            oid=owners.get(name,owners.get(name.split('.',1)[0]))
            if oid is None:raise ValueError('Unclassified native CF record: '+name)
            if name!=oid:self.streams[oid].add(name)
            self.records[name]=oid
        for oid in sorted(source_ids|target_ids):
            if oid in source_ids and oid not in before:raise ValueError('Missing source native object: '+oid)
            if oid in target_ids and oid not in after:raise ValueError('Missing target native object: '+oid)
            if oid not in target_ids and any(self.records.get(name)==oid for name in after):raise ValueError('Deleted native object retains records: '+oid)
            if oid not in source_ids and any(self.records.get(name)==oid for name in before):raise ValueError('New native object already has source records: '+oid)
            streams=self.streams[oid]
            added=tuple(sorted(name for name in streams if name not in before and name in after))
            removed=tuple(sorted(name for name in streams if name in before and name not in after))
            changed=tuple(sorted(name for name in streams if name in before and name in after and before[name]!=after[name]))
            body=before.get(oid)!=after.get(oid)
            if body or added or removed or changed:
                operation='create' if oid not in source_ids else 'delete' if oid not in target_ids else 'change'
                self.objects[oid]=ObjectDelta(oid,operation,body,added,changed,removed)
