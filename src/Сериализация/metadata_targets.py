"""Name references use a final identity index, never fabricated snapshots."""
import metadata_context
from dataclasses import dataclass
from typing import Optional
import native_metadata as s
import metadata_identifiers as ids


@dataclass(frozen=True)
class Target:
    object_id: str
    class_id: str
    parent_id: str
    owner_id: str
    name: str
    children: Optional[frozenset] = None


class Index:
    def __init__(self,targets,renames=None):self.targets=tuple(targets);self.renames=dict(renames or {})

    def find(self,classes,name,parent=None):
        return [row for row in self.targets if row.class_id in classes and row.name==name and (parent is None or row.parent_id==parent)]

    def qualified(self,object_id,seen=()):
        import metadata_structure
        if object_id in seen:raise ValueError('Cyclic reference ownership')
        matches=[row for row in self.targets if row.object_id==object_id]
        if len(matches)!=1:raise ValueError('Missing or ambiguous reference owner')
        row=matches[0];kind=ids.class_labels().get(row.class_id)
        prefix=metadata_structure.profile(kind)['xml_name']+'.'+row.name
        parents=[parent for parent in self.targets if parent.object_id==row.parent_id]
        if len(parents)>1:raise ValueError('Ambiguous reference parent')
        if parents and parents[0].class_id!=ids.class_id('Configuration'):
            prefix=self.qualified(row.parent_id,seen+(object_id,))+'.'+prefix
        return prefix

    def owned_form(self,text,owner,kind):
        import managed_form_profiles
        parents=[row for row in self.targets if row.object_id==owner and row.class_id==ids.class_id(kind)]
        if len(parents)!=1:raise ValueError('Missing or ambiguous form owner')
        prefix=self.qualified(owner)+'.Form.'
        if not text.startswith(prefix):raise ValueError('Invalid or foreign owned form reference')
        name=text[len(prefix):]
        if not name or '.' in name:raise ValueError('Invalid owned form reference')
        cls=ids.class_id(managed_form_profiles.form_kind(kind))
        matches=[row for row in self.find({cls},name,owner) if row.owner_id==s.ZERO]
        if len(matches)!=1 or parents[0].children is None or (matches[0].object_id,cls) not in parents[0].children:
            raise ValueError('Missing, ambiguous or unregistered owned form reference')
        return matches[0].object_id


def index(objects):
    if isinstance(objects,Index):return objects
    return Index(Target(oid,s.val(d[0][2]),s.val(d[0][3]),s.val(d[0][4]),s.val(d[0][9]),
                        frozenset(metadata_context.children(d[0])) if isinstance(d[0][12],list) else None) for oid,d in objects.items())


def creation(kind,oid,name,forms,objects=None,parent=s.ZERO,templates=None):
    import managed_form_profiles
    children=[Target(fid,ids.class_id(managed_form_profiles.form_kind(kind)),oid,s.ZERO,fname,frozenset()) for fname,fid in forms.items()]
    children += [Target(tid,ids.class_id('Template'),oid,s.ZERO,tname,frozenset()) for tname,tid in (templates or {}).items()]
    targets=list(index(objects or {}).targets);existing=[row for row in targets if row.object_id==oid]
    if existing:
        if (len(existing)!=1 or (existing[0].class_id,existing[0].name,existing[0].owner_id)!=(ids.class_id(kind),name,s.ZERO)
                or parent!=s.ZERO and existing[0].parent_id!=parent):raise ValueError('Conflicting creation reference identity')
        if parent==s.ZERO:parent=existing[0].parent_id
        targets=[row for row in targets if row.object_id!=oid]
    owner=Target(oid,ids.class_id(kind),parent,s.ZERO,name,frozenset((row.object_id,row.class_id) for row in children))
    return Index(targets+[owner]+children)


def final(objects,inventory,*,allow_rename=False):
    """The caller has validated the whole export and all creation plans.

    Only class/name/ownership and final child registration are made visible to
    reference readers. Source metadata, versions and snapshots stay unchanged.
    """
    import configuration_export as export
    classes={oid:ids.class_id(export.runtime_kind(row,inventory)) for oid,row in inventory.items()}
    rows=[];renames={}
    for oid,row in inventory.items():
        if oid in objects:
            m=objects[oid][0]
            if (s.val(m[2]),s.val(m[3]))!=(classes[oid],row['parent_id']):raise ValueError('Final reference identity differs from source')
            if s.val(m[9])!=row['name']:
                if not allow_rename:raise ValueError('Final reference identity differs from source')
                renames[oid]=(s.val(m[9]),row['name'])
            owner=s.val(m[4])
        else:owner=s.ZERO
        children=frozenset((key,classes[key]) for key,child in inventory.items() if child['parent_id']==oid)
        rows.append(Target(oid,classes[oid],row['parent_id'],owner,row['name'],children))
    return Index(rows,renames)
