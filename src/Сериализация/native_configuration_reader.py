"""Read native configuration common properties and contained type UUIDs."""
import uuid
import metadata_identifiers as identifiers
import platform_profiles as platforms
from native_metadata import Atom, ZERO, val


ROOT_CLASS = identifiers.class_id('Configuration')


BASIC_FEATURE = "b3b0b503-7bab-411e-bf30-7a7c0925a441"


PROPERTY_SLOTS = {'NamePrefix': 42, 'Vendor': 14, 'Version': 15, 'UpdateCatalogAddress': 16}


ROOT_FEATURE_CLASS = identifiers.group_id('General')


def stored_collections(documents,object_id,platform):
    """Read schema-declared class/count/UUID collections without fixed slots."""
    import metadata_structure
    common_properties(documents,object_id,platform)
    classes={row['item_class_id'] for row in metadata_structure.profile('Configuration')['collections']
             if row['storage']=='stored_name' and row.get('item_class_id')}
    result={};seen=set()
    def walk(node):
        if not isinstance(node,list):return
        if node and isinstance(node[0],Atom) and val(node[0]) in classes:
            key=val(node[0])
            if key in result or len(node)<2 or not isinstance(node[1],Atom) or val(node[1])!=str(len(node)-2):
                raise ValueError('Invalid native configuration child collection')
            values=[]
            for child in node[2:]:
                if not isinstance(child,Atom):raise ValueError('Invalid configuration child UUID')
                oid=str(uuid.UUID(val(child)))
                if oid==ZERO or oid in seen:raise ValueError('Duplicate/zero configuration child UUID')
                seen.add(oid);values.append(oid)
            result[key]=values
            return
        for child in node:walk(child)
    walk(documents)
    return result


def contained_objects(documents,object_id,platform):
    """Read actual contained feature UUIDs from the verified root body."""
    common=common_properties(documents,object_id,platform)
    result={ROOT_FEATURE_CLASS:val(common[1][2]).lower()}
    def ids(node):
        found=[]
        if isinstance(node,list):
            if len(node)==3 and all(isinstance(item,Atom) for item in node) and [val(item) for item in node[:2]]==['1','0']:
                found.append(str(uuid.UUID(val(node[2]))))
            for child in node:found.extend(ids(child))
        return found
    for group in documents[0][3:]:
        if not isinstance(group,list) or len(group)!=2 or not isinstance(group[0],Atom) or val(group[0])==ROOT_FEATURE_CLASS:continue
        found=ids(group[1])
        if len(found)==1:
            key=str(uuid.UUID(val(group[0])))
            if key in result:raise ValueError('Duplicate Configuration contained class')
            result[key]=found[0]
    return result


def common_properties(node, object_id, platform='8.5.4.1878'):
    # Configuration stores common properties under its feature ID, not root UUID.
    if (len(node) != 1 or not isinstance(node[0], list) or len(node[0]) < 2
            or val(node[0][0]) != "2" or not isinstance(node[0][1], list)
            or len(node[0][1]) != 1 or val(node[0][1][0]).lower() != object_id.lower()):
        raise ValueError("Object content UUID does not match the Configuration root")
    if platforms.legacy(platform):
        props = configuration_properties(node, platform)
        wrapper = props[1]
        if not isinstance(wrapper, list) or len(wrapper) != 2 or val(wrapper[0]) != '0':
            raise ValueError('Unsupported 8.5.1 common properties wrapper')
        common = wrapper[1]
        if (not isinstance(common, list) or len(common) != 9 or val(common[0]) != '3'
                or not isinstance(common[1], list) or len(common[1]) != 3
                or [val(v) for v in common[1][:2]] != ['1', '0']
                or not isinstance(common[4], Atom) or not common[4].quoted):
            raise ValueError('Unsupported 8.5.1 common properties layout')
        if str(uuid.UUID(val(common[1][2]))) == ZERO:
            raise ValueError('Zero common properties UUID')
        return common
    found = []
    def walk(n):
        if not isinstance(n, list):
            return
        if (len(n) >= 5 and isinstance(n[0], Atom) and val(n[0]) == "4"
                and isinstance(n[1], list) and len(n[1]) == 3
                and all(isinstance(x, Atom) for x in n[1])
                and [val(x) for x in n[1]][:2] == ["1", "0"]
                and val(n[1][2]).lower() == BASIC_FEATURE):
            found.append(n)
        for child in n:
            walk(child)
    walk(node)
    if len(found) != 1 or not isinstance(found[0][4], Atom) or not found[0][4].quoted:
        raise ValueError("Unsupported common properties layout")
    return found[0]


def configuration_properties(documents, platform='8.5.4.1878'):
    groups = [g for g in documents[0][3:] if isinstance(g, list) and len(g) == 2
              and isinstance(g[0], Atom) and val(g[0]) == ROOT_FEATURE_CLASS]
    if len(groups) != 1:
        raise ValueError('Unsupported Configuration feature layout')
    outer = groups[0][1]
    if len(outer) < 2 or val(outer[0]) != '1' or not isinstance(outer[1], list):
        raise ValueError('Unsupported Configuration feature version')
    props = outer[1]
    count, length = platforms.configuration_layout(platform)
    if len(props) != length or val(props[0]) != str(count):
        raise ValueError('Unsupported Configuration property layout for ' + platform)
    for index in PROPERTY_SLOTS.values():
        if not isinstance(props[index], Atom) or not props[index].quoted:
            raise ValueError('Unsupported string property layout')
    return props
