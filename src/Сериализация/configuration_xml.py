"""Configuration root XML conversion and verified native property layouts."""
import metadata_context
import xml_namespaces
import base64
import copy
import json
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
import metadata_identifiers as identifiers
import platform_profiles as platforms
from native_metadata import Atom, ZERO, atom, render, val


ROOT_CLASS = identifiers.class_id('Configuration')


BASIC_FEATURE = "b3b0b503-7bab-411e-bf30-7a7c0925a441"


PROPERTY_SLOTS = {'NamePrefix': 42, 'Vendor': 14, 'Version': 15, 'UpdateCatalogAddress': 16}


ROOT_FEATURE_CLASS = identifiers.group_id('General')


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


def synonym_value(node):
    if not isinstance(node, list) or not node or int(val(node[0])) * 2 != len(node) - 1:
        raise ValueError('Invalid native Synonym count')
    pairs = []
    for i in range(1, len(node), 2):
        if not all(isinstance(n, Atom) and n.quoted for n in node[i:i + 2]):
            raise ValueError('Unsupported native Synonym layout')
        pairs.append((val(node[i]), val(node[i + 1])))
    if len({p[0] for p in pairs}) != len(pairs):
        raise ValueError('Duplicate native Synonym language')
    return pairs


def xml_property_patches(before_text, after_text, object_id, common, documents, platform='8.5.4.1878', allowed=None,allow_unchanged=False,*,allow_rename=False):
    if '<!DOCTYPE' in before_text.upper() or '<!DOCTYPE' in after_text.upper():
        raise ValueError('DOCTYPE is unsupported')
    before, after = ET.fromstring(before_text), ET.fromstring(after_text)
    def properties(root):
        configs = [e for e in root.iter() if e.tag.rsplit('}', 1)[-1] == 'Configuration']
        if len(configs) != 1 or configs[0].get('uuid', '').lower() != object_id:
            raise ValueError('XML must contain the requested Configuration UUID')
        nodes = [e for e in configs[0] if e.tag.rsplit('}', 1)[-1] == 'Properties']
        if len(nodes) != 1:
            raise ValueError('Missing or duplicate Configuration.Properties')
        return nodes[0]
    source, changed = properties(before), properties(after)
    def canonical(e):
        return (e.tag, sorted(e.attrib.items()), (e.text or '') if not len(e) else (e.text or '').strip(),
                (e.tail or '').strip(), tuple(canonical(c) for c in e))
    def unique(parent, name, required=True):
        nodes = [e for e in parent if e.tag.rsplit('}', 1)[-1] == name]
        if len(nodes) > 1 or (required and not nodes):
            raise ValueError('Missing or duplicate XML property: ' + name)
        return nodes[0] if nodes else None
    import metadata_common_xml
    for index,props in enumerate((source, changed)):
        name = unique(props, 'Name')
        value=name.text or ''
        if name.attrib or len(name):raise ValueError('Invalid Configuration.Name')
        if index==1 and allow_rename and value!=val(common[2]):metadata_common_xml.name_value(name)
        elif value != val(common[2]):
            raise ValueError('Configuration.Name changes are unsupported')
    def xml_synonym(node):
        pairs = []
        for item in node:
            if item.tag != '{http://v8.1c.ru/8.1/data/core}item' or len(item) != 2 or item.attrib:
                raise ValueError('Unsupported XML Synonym item')
            lang, content = unique(item, 'lang'), unique(item, 'content')
            if (lang.tag != '{http://v8.1c.ru/8.1/data/core}lang'
                    or content.tag != '{http://v8.1c.ru/8.1/data/core}content'
                    or len(lang) or len(content) or lang.attrib or content.attrib or not (lang.text or '')):
                raise ValueError('Invalid XML Synonym language or content')
            pairs.append((lang.text, content.text or ''))
        if len({p[0] for p in pairs}) != len(pairs):
            raise ValueError('Duplicate XML Synonym language')
        return pairs
    patches = []
    props = None
    for key in allowed if allowed is not None else (('Name',) if allow_rename else ())+('Comment', 'Synonym', *PROPERTY_SLOTS):
        old, new = unique(source, key, False), unique(changed, key, False)
        if old is None and new is None:
            continue
        if old is None or new is None:
            raise ValueError('Both XML documents must contain property: ' + key)
        if key == 'Synonym':
            token = common[3]
            baseline, value = xml_synonym(old), xml_synonym(new)
            current = synonym_value(token)
            native = [atom(len(value))]
            for lang, content in value:
                native.extend([atom(lang, True), atom(content, True)])
        else:
            if len(old) or len(new):
                raise ValueError('Expected scalar XML property: ' + key)
            if key in ('Name','Comment'):
                token = common[2 if key=='Name' else 4]
            else:
                if props is None:
                    props = configuration_properties(documents, platform)
                token = props[PROPERTY_SLOTS[key]]
            baseline, value, current = old.text or '', new.text or '', val(token)
            native = atom(value, True)
        if baseline != current:
            raise ValueError('Baseline XML ' + key + ' does not match the server snapshot')
        if baseline != value:
            patches.append((token.start, token.end, render(native)))
        # Only value changes are allowed; attributes and unrelated XML remain checked.
        old.text = new.text
        old[:] = copy.deepcopy(list(new))
    if canonical(before) != canonical(after):
        raise ValueError('Unsupported XML changes outside supported Configuration properties')
    if not patches and not allow_unchanged:
        raise ValueError('Supported XML properties have not changed')
    return patches


def configuration_xml_values(after_text, object_id, common, documents, platform, allowed=None,*,allow_rename=False):
    """Read every supported target property, including unchanged values.

    XML validation protects unsupported sections separately. All provided target
    values are serialized, including unchanged values.
    """
    root = ET.fromstring(after_text)
    config = next(e for e in root.iter() if e.tag.rsplit('}',1)[-1]=='Configuration')
    properties = next(e for e in config if e.tag.rsplit('}',1)[-1]=='Properties')
    values = {e.tag.rsplit('}',1)[-1]:e for e in properties}
    result=[]
    for key in allowed if allowed is not None else (('Name',) if allow_rename else ())+('Comment','Synonym',*PROPERTY_SLOTS):
        if key not in values:
            continue
        node=values[key]
        if key=='Synonym':
            token=common[3]; native=[atom(len(node))]
            for item in node:
                native.extend([atom(item[0].text or '',True),atom(item[1].text or '',True)])
        else:
            token=common[2 if key=='Name' else 4] if key in ('Name','Comment') else configuration_properties(documents,platform)[PROPERTY_SLOTS[key]]
            native=atom(node.text or '',True)
        result.append((token.start,token.end,render(native)))
    return result


def configuration_baseline_from_snapshot(after_text, object_id, common, documents, platform, context,*,reference_objects=None):
    """Validate a target XML against the native snapshot, without a prior dump.

    Unmapped properties are accepted only for the verified default native profile.
    Omitted properties remain intact; children and internal IDs cannot be edited.
    """
    if '<!DOCTYPE' in after_text.upper():
        raise ValueError('DOCTYPE is unsupported')
    root = ET.fromstring(after_text)
    local = lambda e: e.tag.rsplit('}', 1)[-1]
    if local(root) != 'MetaDataObject' or len(root) != 1 or local(root[0]) != 'Configuration':
        raise ValueError('Expected one Configuration XML object')
    if any(key != 'version' for key in root.attrib) or root.get('version', '2.21') != '2.21':
        raise ValueError('Unsupported Configuration XML version or attributes')
    config = root[0]
    if config.attrib != {'uuid': object_id}:
        raise ValueError('XML must contain the requested Configuration UUID')
    sections = {}
    for node in config:
        key = local(node)
        if key not in ('Properties', 'InternalInfo', 'ChildObjects') or key in sections or node.attrib:
            raise ValueError('Unsupported or duplicate Configuration section: ' + key)
        sections[key] = node
    if 'Properties' not in sections:
        raise ValueError('Missing Configuration.Properties')
    props = sections['Properties']; names = [local(n) for n in props]
    if len(set(names)) != len(names):
        raise ValueError('Duplicate XML property')
    supported = {'Name', 'Comment', 'Synonym', *PROPERTY_SLOTS}
    for node in props:
        if local(node) in supported and (node.attrib or (local(node) != 'Synonym' and len(node))):
            raise ValueError('Unsupported XML property attributes or children')
    unmapped = [n for n in props if local(n) not in supported]
    def canonical(e):
        return [e.tag, [list(pair) for pair in sorted(e.attrib.items())],
                (e.text or '') if not len(e) else (e.text or '').strip(), [canonical(c) for c in e]]
    if unmapped:
        if not platforms.legacy(platform):
            raise ValueError('Unmapped Configuration properties require the verified legacy profile')
        profile = json.loads(Path(__file__).with_name('configuration_profile_851.json').read_text(encoding='utf-8'))
        native = configuration_properties(documents, platform)
        if render(common[5:]) != profile['common_tail'] or any(render(native[int(i)]) != value for i, value in profile['native_slots'].items()):
            raise ValueError('Source Configuration properties are outside the verified native profile')
        # The default language is a reference, so resolve its actual name from context.
        objects = metadata_context.context_objects(context)
        for node in unmapped:
            key = local(node)
            if key == 'DefaultLanguage':
                lang = val(native[10])
                expected = '' if lang == ZERO else 'Language.' + val(objects[lang][0][9])
                if node.attrib or len(node) or (node.text or '') != expected:
                    raise ValueError('Unsupported Configuration.DefaultLanguage change')
            elif key not in profile['xml_properties'] or canonical(node) != profile['xml_properties'][key]:
                raise ValueError('Unsupported Configuration property: ' + key)
    if 'InternalInfo' in sections:
        actual = contained_objects(documents,object_id,platform)
        expected = {}
        for node in sections['InternalInfo']:
            if local(node) != 'ContainedObject' or node.attrib or len(node) != 2 or [local(n) for n in node] != ['ClassId','ObjectId'] or any(n.attrib or len(n) for n in node):
                raise ValueError('Unsupported Configuration.InternalInfo')
            cls, oid = [(n.text or '').lower() for n in node]
            if cls in expected: raise ValueError('Duplicate internal class')
            expected[cls] = oid
        if expected != actual:
            raise ValueError('XML internal UUIDs do not match native body')
    if 'ChildObjects' in sections:
        import metadata_structure
        objects = metadata_context.context_objects(context)
        expected = []
        for oid, cls in metadata_context.children(metadata_context.context_metadata(base64.b64decode(context), object_id)[0]):
            name = identifiers.class_labels().get(cls)
            if name is None: raise ValueError('Unknown Configuration child class')
            child_name=val(objects[oid][0][9])
            if reference_objects is not None:
                import metadata_targets
                matches=[row for row in metadata_targets.index(reference_objects).targets if row.object_id==oid]
                if len(matches)>1:raise ValueError('Ambiguous final Configuration child')
                if matches:
                    if matches[0].class_id!=cls or matches[0].parent_id!=object_id:raise ValueError('Final Configuration child ownership differs')
                    child_name=matches[0].name
            expected.append((metadata_structure.profile(name)['xml_name'], child_name))
        target = sections['ChildObjects']
        if any(n.attrib or len(n) for n in target) or sorted((local(n), n.text or '') for n in target) != sorted(expected):
            raise ValueError('Configuration child changes are unsupported')
    # Existing validation checks scalar/synonym shape and protects all XML attributes.
    for node in props:
        key = local(node)
        if key in ('Name','Comment'): node.text = val(common[2 if key=='Name' else 4])
        elif key in PROPERTY_SLOTS: node.text = val(configuration_properties(documents, platform)[PROPERTY_SLOTS[key]])
        elif key == 'Synonym':
            node[:] = []
            for lang, content in synonym_value(common[3]):
                item = ET.SubElement(node, '{http://v8.1c.ru/8.1/data/core}item')
                ET.SubElement(item, '{http://v8.1c.ru/8.1/data/core}lang').text = lang
                ET.SubElement(item, '{http://v8.1c.ru/8.1/data/core}content').text = content
    return xml_namespaces.serialize(root)
