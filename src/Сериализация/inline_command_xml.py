"""Owned module stream identities for inline commands."""
import native_metadata as s
from inline_metadata_xml import at

def features(body,layout):
    return [s.val(at(entry,profile['id_path'])) for profile in layout.get('command_collections',{}).values() for entry in body[profile['slot']][2:]]


def streams(body,layout):
    return {s.val(at(entry,profile['id_path'])):s.val(at(entry,profile['id_path']))+profile['module_suffix'] for profile in layout.get('command_collections',{}).values() for entry in body[profile['slot']][2:]}


def preserve_owner_streams(docs,oid,body,kind,platform):
    """Retain owner files and modules proven to belong to its inline commands."""
    import object_xml_profiles as profiles
    import packet_builder
    layout=profiles.layout(kind,platform) if kind in profiles.profiles() else {}
    template=s.Parser(layout['template']).documents()[0] if layout.get('command_collections') else None
    for rule in layout.get('command_collections',{}).values():
        row=body[rule['slot']]
        if (not isinstance(row,list) or len(row)<2 or s.val(row[0])!=s.val(template[rule['slot']][0])
                or s.val(row[1])!=str(len(row)-2)):raise ValueError('Invalid owner command collection')
    commands=features(body,layout)
    if len(set(commands))!=len(commands):raise ValueError('Duplicate owner command UUID')
    owned=streams(body,layout)
    owner_features=docs[0][13]
    if (not owner_features or s.val(owner_features[0])!=str(len(owner_features)-1)
            or len({s.val(value) for value in owner_features[1:]})!=len(owner_features)-1):raise ValueError('Invalid owner feature map')
    if set(owned)-{s.val(value) for value in owner_features[1:]}:raise ValueError('Command stream owner is absent from the feature map')
    return packet_builder.preserve_external_versions(docs,oid,owned.values())


def module_inputs(values,owners):
    if isinstance(values,list):
        if len(values)>1024 or any(not isinstance(entry,dict) or set(entry)!={'object_id','source_text'} for entry in values):raise ValueError('Invalid inline command module array')
        modules={entry['object_id']:entry['source_text'] for entry in values}
        if len(modules)!=len(values):raise ValueError('Duplicate inline command module owner')
    elif isinstance(values,dict):modules=values
    else:raise ValueError('Invalid inline command module input')
    if len(modules)>1024 or set(modules)-set(owners) or any(not isinstance(text,str) for text in modules.values()):raise ValueError('Invalid inline command module owners or texts')
    if sum(len(text.encode('utf-8')) for text in modules.values())>s.MAX_BYTES:raise ValueError('Oversized inline command modules')
    return modules
