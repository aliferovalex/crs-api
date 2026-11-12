"""Read native managed form interfaces and owner binding paths."""
import native_metadata as s

NS = 'http://v8.1c.ru/8.3/xcf/logform'
CORE = 'http://v8.1c.ru/8.1/data/core'
Q = '{' + NS + '}'


class ObjectPaths(dict):
    """Native paths plus the set of bindings that represent tabular collections."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.tables=set();self.types={};self.references={};self.main_types={};self.main_collections=set()


def scalar_type(pattern):
    if isinstance(pattern,list) and len(pattern)==2 and isinstance(pattern[1],list) and pattern[1] and isinstance(pattern[1][0],s.Atom):return s.val(pattern[1][0])
    return None


def tabular_paths(owner,kind,paths):
    import native_tabular as tabular
    import native_form_bindings as bindings
    for entry in tabular.collection(owner,kind):
        common=tabular.common(entry);name='Object.'+s.val(common[2]);oid=s.val(common[1][2])
        if name in paths:raise ValueError('Ambiguous tabular form binding')
        paths[name]=s.Parser('{2,{1},{0,'+oid+'}}').documents()[0];paths.tables.add(name)
        for column,(code,type_code) in bindings.profile()['tabular_standard_fields'].items():
            field=name+'.'+column
            paths[field]=[s.atom(3),[s.atom(1)],[s.atom(0),s.atom(oid)],[s.atom(code)]]
            paths.types[field]=type_code
        for attr in tabular.attributes(entry):
            common=attr[0][1][1][1];field=name+'.'+s.val(common[2])
            if any(field.casefold()==key.casefold() for key in paths):raise ValueError('Ambiguous tabular attribute form binding')
            paths[field]=s.Parser('{3,{1},{0,'+oid+'},{0,'+s.val(common[1][2])+'}}').documents()[0]
            paths.types[field]=scalar_type(attr[0][1][1][2])
    return paths


def object_paths(owner,kind):
    import native_form_bindings as bindings
    profile=bindings.owners().get(kind,{})
    if 'inline_groups' in profile:
        result=ObjectPaths()
        if owner is not None:
            bindings.attach_types(result,owner,kind);bindings.register_fields(result,owner,kind)
            if profile.get('tabular_sections'):tabular_paths(owner,kind,result)
        return result
    return bindings.attach_types(_object_paths(owner,kind),owner,kind)


def _object_paths(owner,kind):
    if kind=='CommonForm':return ObjectPaths()
    if kind in ('DataProcessor','Report'):return ObjectPaths()
    import native_form_profiles as profiles
    if kind in profiles.KINDS:return ObjectPaths()
    raise ValueError('Unsupported form owner kind')


def interface(raw):
    docs = s.Parser(raw.decode('utf-8-sig')).documents()
    if len(docs) != 1 or len(docs[0]) != 10 or s.val(docs[0][0]) != '4' or s.val(docs[0][1][0]) != '59':
        raise ValueError('Unsupported managed interface layout')
    return docs[0]
