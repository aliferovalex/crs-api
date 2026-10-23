"""Whole companion files mapped to native streams by the object profile."""
import base64
from dataclasses import dataclass
from pathlib import Path
import native_metadata as s
import object_xml_profiles as profiles
import xdto_packages


@dataclass(frozen=True)
class Content:
    data: bytes
    # None preserves body dependencies; a tuple replaces file-owned relations,
    # retaining the object's mandatory parent relation.
    relations: tuple = None


def validate(raw,rule,definition):
    if rule['codec']=='xdto-package':xdto_packages.declaration(definition,raw)
    elif rule['codec']=='role-rights':
        import role_rights_xml
        role_rights_xml.parse(raw)
    else:raise ValueError('Unsupported companion file codec')
    return raw


def inputs(kind,definition,data):
    rules=profiles.content_files(kind)
    if not isinstance(data,dict) or set(data)-set(rules):raise ValueError('Unsupported companion file data')
    if {name for name,rule in rules.items() if rule.get('required')}-set(data):raise ValueError('Missing required companion file data')
    result={}
    for name,encoded in data.items():
        if not isinstance(encoded,str) or len(encoded)>s.MAX_BYTES*2:raise ValueError('Invalid or oversized companion file data')
        try:raw=base64.b64decode(encoded,validate=True)
        except ValueError:raise ValueError('Invalid companion file Base64') from None
        if len(raw)>s.MAX_BYTES:raise ValueError('Oversized companion file')
        result[name]=validate(raw,rules[name],definition)
    return result


def convert(kind,definition,data,request=None):
    result={};rules=profiles.content_files(kind)
    for name,raw in inputs(kind,definition,data).items():
        if rules[name]['codec']=='role-rights':
            import role_rights_xml,role_rights_native,role_metadata_context
            definitions=(request or {}).get('_metadata_definitions')
            if definitions is None and (request or {}).get('metadata_definitions') is not None:
                import metadata_definitions
                rows=request['metadata_definitions']
                if not isinstance(rows,list):raise ValueError('Metadata definitions must be an array')
                try:definitions=metadata_definitions.Index(metadata_definitions.Definition(**row) for row in rows)
                except TypeError:raise ValueError('Invalid metadata definitions') from None
                if (request or {}).get('context') is not None:
                    import metadata_context,metadata_identifiers
                    objects=metadata_context.context_objects(request['context'])
                    for entry in definitions.entries:
                        if entry.stored_id not in objects:raise ValueError('Role definition is absent from current repository metadata')
                        metadata=objects[entry.stored_id][0]
                        if entry.stored:
                            if (s.val(metadata[2])!=metadata_identifiers.class_id(entry.kind)
                                    or s.val(metadata[9])!=entry.name or s.val(metadata[3])!=entry.parent_id):
                                raise ValueError('Role definition differs from current repository metadata')
                        elif entry.object_id not in {s.val(value) for value in metadata[13][1:]}:
                            raise ValueError('Role inline definition is absent from current repository features')
            context=role_metadata_context.Context(definitions) if definitions is not None else None
            raw=role_rights_xml.compile(raw,context)
            result[name]=Content(raw,tuple((key,1) for key in sorted(role_rights_native.file_references(raw))))
        else:result[name]=Content(raw)
    return result


def definition_context(path,kind,data,request):
    if kind!='Role' or 'Rights' not in data:return {}
    import role_rights_xml,metadata_definitions
    raw=base64.b64decode(data['Rights'],validate=True)
    if not role_rights_xml.parse(raw).findall(role_rights_xml.Q+'object'):return {}
    definitions=request.get('_metadata_definitions')
    if definitions is None:
        import configuration_export
        base=Path(path).resolve().parent.parent
        if not (base/'Configuration.xml').is_file():raise ValueError('Role Rights.xml requires its hierarchical configuration export')
        _,_,inventory,_=configuration_export.inventory(base)
        definitions=metadata_definitions.from_inventory(inventory)
    return dict(metadata_definitions=role_rights_xml.required_definitions(raw,definitions))


def apply_relations(metadata,files):
    controlled=[content for content in files.values() if content.relations is not None]
    if not controlled:return
    relations={}
    for content in controlled:
        for key,flag in content.relations:
            if key in relations and relations[key]!=flag:raise ValueError('Conflicting file relations')
            relations[key]=flag
    parent=s.val(metadata[3])
    if parent!=s.ZERO:relations[parent]=1
    metadata[14]=[s.atom(len(relations))]+[s.atom(key) for key in relations]+[s.atom(flag) for flag in relations.values()]


def companion(path,kind,definition):
    data={}
    for name,rule in profiles.content_files(kind).items():
        file=Path(path).with_suffix('')/'Ext'/rule['file']
        if not file.is_file():
            if rule.get('required'):raise ValueError('Missing companion file: '+str(file))
            continue
        if file.stat().st_size>s.MAX_BYTES:raise ValueError('Oversized companion file')
        data[name]=base64.b64encode(file.read_bytes()).decode()
    inputs(kind,definition,data)
    return data
