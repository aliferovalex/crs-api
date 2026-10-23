"""Recompile retained forms when their owner bindings change without XML edits."""
import copy
from pathlib import Path
from xml.etree import ElementTree as E
import native_metadata as s
import managed_form_profiles as profiles
import managed_form_xml as forms
import native_collection_editor as collections
import serialization_context as contexts
import preparation_plan as preparation
import configuration_export as export


def candidates(target,changes,objects,baseline_directory=None):
    import metadata_owner_change
    baseline=export.inventory(baseline_directory)[2] if baseline_directory is not None else None
    def may_change(row):
        if baseline_directory is None:return True
        before=E.fromstring(preparation.read(Path(baseline_directory)/baseline[row['object_id']]['path']))
        after=E.fromstring(row['object_xml'])
        for root in (before,after):
            props=root[0].find(preparation.Q+'Properties')
            if props is not None:
                for node in list(props):
                    if node.tag in (preparation.Q+'Comment',preparation.Q+'Synonym'):props.remove(node)
        return metadata_owner_change.retained_xml(before,row['kind'],ignore_form_properties=True)!=metadata_owner_change.retained_xml(after,row['kind'],ignore_form_properties=True)
    owners={row['object_id'] for row in changes if row['kind'] in profiles.owner_profiles() and may_change(row)}
    changed={row['object_id'] for row in changes}
    return [oid for oid,row in target.items() if row['kind']=='Form' and row['parent_id'] in owners and oid in objects and oid not in changed]


def binding_delta(source,target,kind,metadata,objects):
    # Changing just common properties or stored child collections must not
    # require understanding opaque field types in an otherwise retained owner.
    baseline=copy.deepcopy(target)
    old_common=profiles.owner_common(source,kind);new_common=profiles.owner_common(baseline,kind)
    new_common[:]=copy.deepcopy(old_common)
    for row in collections.inspect(source,kind,metadata,objects):
        parent=baseline
        for slot in row['path'][:-1]:parent=parent[slot]
        parent[row['path'][-1]]=copy.deepcopy(collections.at(source,row['path']))
    if s.render(baseline)==s.render(source):return set(),None
    old=forms.object_paths(source,kind);new=forms.object_paths(target,kind)
    def signature(paths,key):
        return (s.render(paths[key]) if key in paths else None,paths.types.get(key),key in paths.tables)
    return {key for key in set(old)|set(new) if signature(old,key)!=signature(new,key)},new


def changes(request,plan,objects,owner_bodies):
    if not plan['dependent_form_ids']:return []
    _,_,target,_=export.inventory(request['directory']);deltas={};result=[]
    for oid in plan['dependent_form_ids']:
        record=target[oid];parent=record['parent_id'];kind=export.runtime_kind(target[parent],target)
        if parent not in deltas:
            frame=contexts.read(dict(request,snapshot=request['snapshots'][parent]),parent)
            source=s.Parser(s.inflate(frame.data).decode('utf-8-sig')).documents()[0]
            deltas[parent]=binding_delta(source,owner_bodies[parent],kind,frame.metadata,objects)
        delta,paths=deltas[parent]
        if not delta:continue
        path=Path(request['directory'])/record['path'];text=preparation.read(path.with_suffix('')/'Ext/Form.xml')
        root=E.fromstring(text);main=[]
        for attr in root.findall(forms.Q+'Attributes/'+forms.Q+'Attribute'):
            if attr.findtext(forms.Q+'MainAttribute')=='true':main.append(attr.get('name'))
        affected=False
        for node in root.iter(forms.Q+'DataPath'):
            value=node.text or ''
            for name in main:
                if value!=name and not value.startswith(name+'.'):continue
                key='Object'+value[len(name):]
                if key not in delta:continue
                if key not in paths:raise ValueError('Retained form '+record['name']+' refers to unavailable owner DataPath: '+value)
                affected=True
        if affected:result.append(preparation.plan(dict(xml_path=str(path),context=request['context'],platform=request['platform'])))
    return result
