"""Read repository identity facts from whole XML declarations and compiled CF.

No application property is serialized here. Declared ownership must be proven
by the compiled native identity, UUIDs and schema-declared stored collections.
"""
from dataclasses import dataclass
import uuid
import configuration_export as export
import native_metadata as s
import native_object_reader
import native_configuration_reader
import metadata_structure
import native_form_bindings

XR='{http://v8.1c.ru/8.3/xcf/readable}'


def identifier(value):
    value=str(uuid.UUID(value))
    if value==s.ZERO:raise ValueError('Zero declared metadata identity')
    return value


def atoms(node):
    result=set()
    def visit(value):
        if isinstance(value,list):
            for item in value:visit(item)
        elif not value.quoted:
            try:result.add(str(uuid.UUID(s.val(value))))
            except ValueError:pass
    visit(node);return result


def features(record):
    oid=record['id'];values=[]
    for node in record['node'].iter():
        if 'uuid' in node.attrib:
            value=identifier(node.get('uuid'))
            if node is not record['node']:values.append(value)
        if node.tag==XR+'ContainedObject':values.append(identifier(node.findtext(XR+'ObjectId')))
    if oid in values or len(values)!=len(set(values)):raise ValueError('Duplicate declared metadata feature identity')
    return tuple(values)


def generated(record):
    result=[]
    for node in record['node'].iter(XR+'GeneratedType'):
        for field in ('TypeId','ValueId'):
            value=node.findtext(XR+field)
            if value:result.append(identifier(value))
    if len(result)!=len(set(result)):raise ValueError('Duplicate declared generated type identity')
    return frozenset(result)


def common_identity(body,oid,name=None):
    matches=[]
    def visit(node):
        if not isinstance(node,list):return
        if (len(node)>=3 and isinstance(node[0],s.Atom) and s.val(node[0])=='3'
                and isinstance(node[1],list) and len(node[1])==3 and all(isinstance(v,s.Atom) for v in node[1])
                and s.val(node[1][0])=='1' and s.val(node[1][2])==oid):
            if not isinstance(node[2],s.Atom) or not node[2].quoted or name is not None and s.val(node[2])!=name:raise ValueError('Compiled common metadata name differs from XML')
            matches.append(node)
        for child in node:visit(child)
    visit(body)
    if len(matches)!=1:raise ValueError('Missing or ambiguous compiled common identity: '+oid)


def collection_class(body,members):
    """A nonempty declared member set identifies one native collection row."""
    wanted=set(members);matches=[]
    if not wanted:raise ValueError('Cannot infer the class of an empty native collection')
    def visit(node):
        if not isinstance(node,list):return
        if len(node)==len(wanted)+2 and all(isinstance(v,s.Atom) and not v.quoted for v in node):
            try:
                cls=identifier(s.val(node[0]));count=int(s.val(node[1]));values=[identifier(s.val(v)) for v in node[2:]]
                if s.val(node[1])==str(count) and count==len(wanted) and len(set(values))==count and set(values)==wanted:matches.append(cls)
            except (ValueError,TypeError):pass
        for child in node:visit(child)
    visit(body)
    if len(matches)!=1:raise ValueError('Missing or ambiguous native collection for declared members')
    return matches[0]


def bind_class_ids(inventory,image):
    """Fill missing schema UUIDs only from uniquely matched CF collections."""
    owned=set(inventory);children={}
    for oid,record in inventory.items():
        owned.update(features(record));owned.update(generated(record))
        children.setdefault((record['parent_id'],record['kind']),[]).append(oid)
    for parent,record in inventory.items():
        missing=[row for row in metadata_structure.profile(record['kind'])['collections'] if row['storage']=='stored_name' and not row.get('item_class_id')]
        body=None
        for rule in missing:
            members=children.get((parent,rule['item_type']),[])
            if not members:continue
            if body is None:body=s.Parser(image[parent].decode('utf-8-sig')).documents()
            cls=collection_class(body,members)
            if cls in owned:raise ValueError('Native collection class overlaps an owned identity')
            for oid in members:
                previous=inventory[oid].get('_class_id')
                if previous and previous!=cls:raise ValueError('Conflicting native class binding')
                inventory[oid]['_class_id']=cls


@dataclass(frozen=True)
class Facts:
    object_id: str
    class_id: str
    parent_id: str
    name: str
    features: tuple
    generated: frozenset
    children: dict


def read(record,inventory,image,platform='8.5.1.1529'):
    oid=record['id'];body=s.Parser(image[oid].decode('utf-8-sig')).documents()
    native_form_bindings.validate_owner_properties(record['node'],body[0],record['kind'])
    declared_features=features(record);declared_generated=generated(record);native=atoms(body)
    owned=[oid,*declared_features,*declared_generated]
    if len(owned)!=len(set(owned)):raise ValueError('Object, feature and generated identities overlap')
    if not {oid,*declared_features,*declared_generated}<=native:raise ValueError('Declared metadata identities are absent from compiled CF: '+oid)
    common=oid
    if record['kind']=='Configuration':
        expected={node.findtext(XR+'ClassId'):node.findtext(XR+'ObjectId') for node in record['node'].iter(XR+'ContainedObject')}
        if expected!=native_configuration_reader.contained_objects(body,oid,platform):raise ValueError('Compiled configuration features differ from XML')
        rows=[node.findtext(XR+'ObjectId') for node in record['node'].iter(XR+'ContainedObject') if node.findtext(XR+'ClassId')==native_configuration_reader.ROOT_FEATURE_CLASS]
        if len(rows)!=1:raise ValueError('Configuration lacks one common feature identity')
        common=rows[0]
    for node in record['node'].iter():
        if node is not record['node'] and 'uuid' in node.attrib:
            common_identity(body,identifier(node.get('uuid')),node.findtext(export.Q+'Properties/'+export.Q+'Name'))
    common_identity(body,common,record['name'])
    expected={key:export.class_id(row,inventory) for key,row in inventory.items() if row['parent_id']==oid}
    groups=native_object_reader.stored_collections(body,record['kind'],expected.values())
    actual={key:cls for cls,children in groups.items() for key in children}
    if actual!=expected:raise ValueError('Compiled stored children differ from complete XML: '+oid)
    return Facts(oid,export.class_id(record,inventory),record['parent_id'],record['name'],declared_features,declared_generated,groups)


class TypeIndex:
    """Generated type names are declarations, not a list of supported classes."""
    def __init__(self,inventory,image,platform='8.5.1.1529'):
        bind_class_ids(inventory,image)
        self.inventory=inventory;self.image=image;self.platform=platform
        self.aliases={};self.owners={};self.feature_owners={};self._facts={}
        for oid,record in inventory.items():
            for value in features(record):
                if value in self.feature_owners:raise ValueError('Feature identity belongs to multiple objects')
                self.feature_owners[value]=oid
            for value in generated(record):
                if value in self.owners:raise ValueError('Generated identity belongs to multiple objects')
                self.owners[value]=oid
            for node in record['node'].iter(XR+'GeneratedType'):
                name=node.get('name');value=node.findtext(XR+'TypeId')
                if not name or not value:raise ValueError('Incomplete generated type declaration')
                alias='cfg:'+name
                if alias in self.aliases:raise ValueError('Ambiguous generated type name: '+alias)
                self.aliases[alias]=(identifier(value),oid)

    def facts(self,oid):
        if oid not in self._facts:self._facts[oid]=read(self.inventory[oid],self.inventory,self.image,self.platform)
        return self._facts[oid]

    def reference(self,value):
        import metadata_type_sets,metadata_identifiers
        if value in metadata_type_sets.profile():
            roots=[oid for oid,row in self.inventory.items() if row['kind']=='Configuration']
            if len(roots)!=1:raise ValueError('Compiled type groups require one configuration root')
            root=roots[0];self.facts(root)
            cls=metadata_identifiers.group_id(metadata_type_sets.groups()[value])
            entries=[node.findtext(XR+'ObjectId') for node in self.inventory[root]['node'].iter(XR+'ContainedObject') if node.findtext(XR+'ClassId')==cls]
            if len(entries)!=1:raise ValueError('Missing compiled type group feature')
            return metadata_type_sets.profile()[value],entries[0]
        if value not in self.aliases:raise ValueError('Unresolved compiled metadata type: '+value)
        native,owner=self.aliases[value];self.facts(owner)
        return native,owner

    def resolve_required(self,values):
        return {value:self.reference(value)[0] for value in sorted(values)}

    def object_ids_required(self,values):
        return {self.reference(value)[1] for value in values}

    def owner_for_generated(self,value):
        owner=self.owners.get(value)
        if owner is not None:self.facts(owner)
        return owner
