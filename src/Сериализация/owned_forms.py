"""Native managed-form collection lookup and positional order."""
import metadata_identifiers
import native_metadata as s
import managed_form_profiles as profiles

def collection(body,kind):
    cls=metadata_identifiers.class_id(profiles.form_kind(kind));found=[]
    def walk(node):
        if not isinstance(node,list):return
        if len(node)>=2 and isinstance(node[0],s.Atom) and s.val(node[0])==cls:found.append(node)
        for child in node:walk(child)
    walk(body)
    if len(found)!=1:raise ValueError('Missing or ambiguous native form collection')
    row=found[0]
    if int(s.val(row[1]))!=len(row)-2 or len({s.val(v) for v in row[2:]})!=len(row)-2:raise ValueError('Invalid native form collection')
    return row


def positions(body,kind):return {s.val(value):i for i,value in enumerate(collection(body,kind)[2:])}
