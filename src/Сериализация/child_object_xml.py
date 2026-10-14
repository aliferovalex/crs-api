"""Whole-XML references to independently stored children of a metadata object."""
import metadata_serializer as s
import metadata_identifiers as ids


def resolve(node,profile,owner,objects):
    if node.attrib or len(node) or not node.text or node.text.strip()!=node.text:
        raise ValueError('Expected a child object name reference')
    cls=ids.class_id(profile['kind'])
    matches=[oid for oid,docs in objects.items() if s.val(docs[0][2])==cls
             and s.val(docs[0][3])==owner and s.val(docs[0][9])==node.text]
    if len(matches)!=1:raise ValueError('Missing or ambiguous child reference: '+node.text)
    return matches[0]


def validate(source,target,layout,metadata,objects,removed=()):
    """Preserve a complete existing child set, including its positional order."""
    import constant_serializer as c
    pairs=c.children(metadata);checked=[]
    for profile in layout.get('child_collections',{}).values():
        cls=ids.class_id(profile['kind']);old=source[profile['slot']];new=target[profile['slot']]
        for row in (old,new):
            if (len(row)<2 or s.val(row[0])!=cls or s.val(row[1])!=str(len(row)-2)
                    or len({s.val(key) for key in row[2:]})!=len(row)-2):
                raise ValueError('Invalid separately stored child collection')
        old_ids=[s.val(key) for key in old[2:]]
        if [oid for oid in old_ids if oid not in removed]!=[s.val(key) for key in new[2:]]:
            raise ValueError('Existing child references and order must be preserved')
        expected={oid for oid,kind in pairs if kind==cls}
        if set(old_ids)!=expected:raise ValueError('Body/context child collection mismatch')
        positions=[]
        for oid in old_ids:
            docs=objects.get(oid)
            if (docs is None or s.val(docs[0][2])!=cls or s.val(docs[0][3])!=s.val(metadata[1]) or s.val(docs[0][4])!=s.ZERO
                    or not s.val(docs[0][10]).isdecimal()):
                raise ValueError('Child identity, parent or position differs from collection')
            positions.append(int(s.val(docs[0][10])))
            checked.append((oid,cls))
        if positions!=sorted(set(positions)):raise ValueError('Child positions are duplicated or out of order')
    if set(checked)!=set(pairs):raise ValueError('Unsupported separately stored child collection')
    return pairs
