"""Read inline metadata feature UUIDs and their scopes."""
import native_metadata as s


def features(body,layout):
    result=[s.val(entry[0][1][1][1][1][2]) for profile in layout.get('inline_collections',{}).values() for entry in body[profile['slot']][2:]]
    if 'values_slot' in layout:
        result.extend(s.val(entry[0][1][1][2]) for entry in body[layout['values_slot']][2:])
    import native_tabular as tabular
    for profile in layout.get('tabular_collections',{}).values():
        for entry in body[profile['slot']][2:]:result.extend(tabular.feature_ids(entry))
    import native_commands as commands
    result.extend(commands.features(body,layout))
    import native_inline
    for rule in layout.get('structured_collections',{}).values():
        for entry in native_inline.entries(body,rule):result.extend(oid for oid,_ in native_inline.identities(entry,rule))
    if len(set(result))!=len(result):raise ValueError('Duplicate inline feature UUID')
    return result


def scopes(body,layout):
    result={s.val(entry[0][1][1][1][1][2]):name for name,profile in layout.get('inline_collections',{}).items() for entry in body[profile['slot']][2:]}
    if 'values_slot' in layout:
        result.update((s.val(entry[0][1][1][2]),'EnumValue') for entry in body[layout['values_slot']][2:])
    import native_tabular as tabular
    for name,profile in layout.get('tabular_collections',{}).items():
        for entry in body[profile['slot']][2:]:
            oid=s.val(tabular.common(entry)[1][2]);result[oid]=name
            for attr in tabular.attributes(entry):result[s.val(attr[0][1][1][1][1][2])]=name+'.'+oid
    import native_commands as commands
    for name,profile in layout.get('command_collections',{}).items():
        for entry in body[profile['slot']][2:]:result[s.val(commands.at(entry,profile['id_path']))]=name
    import native_inline
    for rule in layout.get('structured_collections',{}).values():
        for entry in native_inline.entries(body,rule):result.update(native_inline.identities(entry,rule))
    return result
