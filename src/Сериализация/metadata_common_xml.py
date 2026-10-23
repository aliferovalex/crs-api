"""Common metadata XML properties without constructing an intermediate object."""
import re
from xml.etree import ElementTree as E
import native_metadata as s
import metadata_localized_xml as localized
import xml_namespaces

Q = '{' + xml_namespaces.MD + '}'


def scalar_value(text,rule):
    """Read a finite enum, canonical nonnegative integer or literal text."""
    if rule.get('string'):
        if '\0' in text or len(text.encode('utf-8'))>s.MAX_BYTES:raise ValueError('Invalid metadata string value')
        return text
    if 'values' in rule:
        if text not in rule['values']:raise ValueError('Unsupported metadata scalar value')
        return str(rule['values'][text])
    bounds=rule['integer']
    if not re.fullmatch(r'0|[1-9][0-9]*',text) or not bounds['min']<=int(text)<=bounds['max']:
        raise ValueError('Invalid metadata integer value')
    return str(int(text))


def scalar_text(value,rule):
    if rule.get('string') and (isinstance(value,list) or not value.quoted):raise ValueError('Expected a quoted native metadata string')
    if 'values' not in rule:return scalar_value(s.val(value),rule)
    labels=[label for label,number in rule['values'].items() if str(number)==s.val(value)]
    if len(labels)!=1:raise ValueError('Unknown native scalar property')
    return labels[0]


def canonical(node):
    return [node.tag, dict(node.attrib), (node.text or '') if not len(node) else (node.text or '').strip(),
            [canonical(child) for child in node]]


def name_value(node):
    if node is None or node.attrib or len(node) or not re.fullmatch(r'[^\W\d]\w{0,79}', node.text or '', re.UNICODE):
        raise ValueError('Invalid metadata Name')
    return node.text


def patch(raw,path,before,after,oid,*,allow_rename=False):
    """Patch verified common fields, retaining all other native bytes."""
    docs=s.Parser(raw.decode('utf-8-sig')).documents()
    if len(docs)!=1:raise ValueError('Unsupported common property body documents')
    common=docs[0]
    try:
        for index in path:common=common[index]
        if (not isinstance(common,list) or len(common)<5 or s.val(common[1][2])!=oid
                or not isinstance(common[2],s.Atom) or not common[2].quoted
                or not isinstance(common[4],s.Atom) or not common[4].quoted):raise ValueError('Native common property identity differs')
    except (IndexError,TypeError):raise ValueError('Unsupported common property layout') from None
    import copy
    def read(root):
        props=root[0].findall(Q+'Properties')
        if len(props)!=1 or props[0].attrib:raise ValueError('Missing or invalid common Properties')
        fields={}
        for key in ('Name','Synonym','Comment'):
            values=props[0].findall(Q+key)
            if len(values)>1:raise ValueError('Duplicate common property: '+key)
            if values:fields[key]=values[0]
        result=copy.deepcopy(common);apply(result,fields,oid)
        return result
    old=read(before);new=read(after)
    if s.render(old[2:5])!=s.render(common[2:5]):raise ValueError('Source common properties differ from native snapshot')
    if s.val(new[2])!=s.val(common[2]) and not allow_rename:raise ValueError('Owner rename requires a complete-export plan')
    text=raw.decode('utf-8-sig');patches=[]
    for index in (2,3,4):
        token=common[index];replacement=s.render(new[index])
        if s.render(token)!=replacement:patches.append((token.start,token.end,replacement))
    for start,end,value in sorted(patches,reverse=True):text=text[:start]+value+text[end:]
    return (b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'')+text.encode('utf-8'),s.val(new[2])


def apply(common, fields, oid):
    name=name_value(fields.get('Name'))
    comment = fields.get('Comment')
    if comment is not None and (comment.attrib or len(comment)):
        raise ValueError('Invalid metadata Comment')
    common[1][2] = s.atom(oid)
    common[2] = s.atom(name, True)
    common[3] = localized.read(fields.get('Synonym'), 'Synonym')
    common[4] = s.atom(comment.text or '' if comment is not None else '', True)
    return name


def read(props, oid, platform='8.5.1.1529'):
    import platform_profiles
    fields = {node.tag.removeprefix(Q): node for node in props}
    if props.attrib or len(fields) != len(props) or any(node.tag != Q + key for key, node in fields.items()):
        raise ValueError('Duplicate or foreign metadata property')
    common = s.Parser('{3,{1,0,00000000-0000-0000-0000-000000000000},"",{0},"",0,0,00000000-0000-0000-0000-000000000000,0}').documents()[0]
    if not platform_profiles.legacy(platform):
        common[0]=s.atom(4)
        common.extend([s.atom(0),s.atom(0),s.atom(3)])
    return apply(common, fields, oid), common


def write(props, common):
    E.SubElement(props, Q + 'Name').text = s.val(common[2])
    synonym = E.SubElement(props, Q + 'Synonym')
    values = common[3]
    if len(values) != 1 + 2 * int(s.val(values[0])):
        raise ValueError('Invalid native Synonym count')
    for index in range(1, len(values), 2):
        item = E.SubElement(synonym, localized.CORE + 'item')
        E.SubElement(item, localized.CORE + 'lang').text = s.val(values[index])
        E.SubElement(item, localized.CORE + 'content').text = s.val(values[index + 1])
    localized.read(synonym, 'Synonym')
    E.SubElement(props, Q + 'Comment').text = s.val(common[4])
