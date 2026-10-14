"""Pinned v8unpack assembly; our adapters supply its JSON/raw model.

Repository framing/version metadata stays outside this backend. Formatting is
normalized after assembly to retain the verified native CRLF representation.
"""
import copy,json,re,sys,tempfile
from pathlib import Path

VERSION='1.2.13'


def runtime():
    local=Path(__file__).resolve().parents[2]/'.python-deps'
    if local.is_dir() and str(local) not in sys.path:sys.path.insert(0,str(local))
    try:
        from v8unpack.version import __version__
        from v8unpack.json_container_decoder import JsonContainerDecoder
    except ImportError as error:
        raise ValueError('Install serializer requirements.txt with the selected Python: '+str(error)) from None
    if __version__!=VERSION:raise ValueError('Expected v8unpack '+VERSION+', got '+__version__)
    return JsonContainerDecoder


def to_model(node):
    """v8unpack keeps scalar tokens quoted in the strings of its raw arrays."""
    import metadata_serializer as s
    if isinstance(node,list):return [to_model(v) for v in node]
    return s.render(node)


def signature(node):
    import metadata_serializer as s
    if isinstance(node,list):return [signature(v) for v in node]
    value=s.val(node)
    if not node.quoted and value.startswith('#base64:'):value='#base64:'+''.join(value[8:].split())
    return node.quoted,value


def assemble(model):
    """Build JSON/raw through upstream, validate and preserve native formatting."""
    import metadata_serializer as s
    decoder=runtime()()
    # Upstream guesses Base64 for any long token, including quoted BSL text.
    # Mask long quoted tokens before assembly and restore them in one pass.
    tokens=[]
    def gather(node):
        if isinstance(node,list):
            for v in node:gather(v)
        else:tokens.append(node)
    gather(model);replacements={}
    def protect(node):
        if isinstance(node,list):return [protect(v) for v in node]
        if isinstance(node,str) and node.startswith('"') and len(node)>64:
            index=len(replacements)
            while True:
                marker='"__crs_v8_token_'+str(index)+'__"'
                if not any(marker in t for t in tokens) and marker not in replacements:break
                index+=1
            replacements[marker]=node;return marker
        return node
    try:text=decoder.encode_root_object(protect(model))
    except Exception as error:raise ValueError('v8unpack native assembly failed: '+str(error)) from None
    if replacements:text=re.sub('|'.join(re.escape(k) for k in replacements),lambda m:replacements[m.group()],text)
    docs=s.Parser(text).documents()
    # Upstream can rewrap Base64; preserve source tokens after checking structure.
    wanted=s.Parser(','.join(_raw(v) for v in model)).documents()
    if signature(docs)!=signature(wanted):
        def mismatch(a,b,path=()):
            if isinstance(a,list) and isinstance(b,list):
                if len(a)!=len(b):return path+('length',len(a),len(b))
                for i,(x,y) in enumerate(zip(a,b)):
                    if signature(x)!=signature(y):return mismatch(x,y,path+(i,))
            return path+('scalar',)
        raise ValueError('v8unpack changed native object values during assembly at '+str(mismatch(docs,wanted)))
    def restore_base64(actual,source):
        if isinstance(actual,list):
            for a,b in zip(actual,source):restore_base64(a,b)
        elif not source.quoted and s.val(source).startswith('#base64:'):actual.value=source.value
    restore_base64(docs,wanted)
    return b'\xef\xbb\xbf'+','.join(s.render_native_text(v) for v in docs).encode('utf-8')


def _raw(node):
    if isinstance(node,list):return '{'+','.join(_raw(v) for v in node)+'}'
    if not isinstance(node,str):raise ValueError('Invalid v8unpack raw model token')
    return node


def form_model(form):
    """Separate interface, props, commands and element tree using upstream rules."""
    runtime()
    from v8unpack.MetaDataObject.Form.FormCore import FormCore
    from v8unpack.MetaDataObject.Form.FormElements4.FormElements4 import FormElements4
    state=FormCore(options={'obj_version':'803'},obj_version='9')
    state.header={'uuid':'00000000-0000-0000-0000-000000000000','name':'XMLForm','Тип формы':'1'}
    state.parent_container_uuid=None
    expected=to_model([form])
    state.form=[copy.deepcopy(expected)]
    decoder=FormElements4(state)
    try:decoder.decode('', '', '', state.form[0][0])
    except Exception as error:raise ValueError('v8unpack form model conversion failed: '+str(error)) from None
    return {'form':state.form,'expected':expected,'elements':{'params':state.params,'props':state.props,
        'commands':state.commands,'tree':state.elements_tree,'data':state.elements_data}}


def table_offsets(entry):
    """Use upstream counters; column insertion shifts the table's tail slots."""
    runtime()
    from v8unpack.MetaDataObject.Form.FormElements4.Table import Table
    from v8unpack.helper import calc_offset
    raw=to_model(entry)
    try:return {'name':Table.get_name_node_offset(raw),'path':Table.get_prop_link_offset(raw),
                'children':calc_offset([(4,1),(50,2),(7,0)],raw)}
    except Exception as error:raise ValueError('Unsupported table layout: '+str(error)) from None


def group_offsets(entry):
    """Group includes ordinary groups, page containers and individual pages."""
    runtime()
    from v8unpack.MetaDataObject.Form.FormElements4.Group import Group
    from v8unpack.helper import calc_offset
    raw=to_model(entry)
    try:return {'name':Group.get_name_node_offset(raw),
                'children':calc_offset([(3,1),(1,1),(17,0)],raw)}
    except Exception as error:raise ValueError('Unsupported group layout: '+str(error)) from None


def field_offsets(entry):
    """Shared upstream field handler for input, checkbox and label variants."""
    runtime()
    from v8unpack.MetaDataObject.Form.FormElements4.Field import Field
    raw=to_model(entry)
    try:return {'name':Field.get_name_node_offset(raw),'path':Field.get_prop_link_offset(raw)}
    except Exception as error:raise ValueError('Unsupported field layout: '+str(error)) from None


def assemble_form(model):
    runtime()
    from v8unpack.MetaDataObject.Form.FormCore import FormCore
    from v8unpack.MetaDataObject.Form.FormElements4.FormElements4 import FormElements4
    state=FormCore(options={'obj_version':'803'},obj_version='9')
    state.header={'uuid':'00000000-0000-0000-0000-000000000000','name':'XMLForm','Тип формы':'1'}
    state.parent_container_uuid=None;state.form=copy.deepcopy(model['form'])
    # Upstream accepts its elem.json format. Temp directories are per invocation.
    with tempfile.TemporaryDirectory(prefix='crs-v8unpack-') as directory:
        Path(directory,'Form.elem.json').write_text(json.dumps(model['elements'],ensure_ascii=False),encoding='utf-8')
        try:FormElements4(state).encode(directory,'Form',directory,state.form[0][0])
        except Exception as error:raise ValueError('v8unpack form assembly failed: '+str(error)) from None
    result=assemble(state.form[0])
    import metadata_serializer as s
    expected=s.Parser(','.join(_raw(v) for v in model['expected'])).documents()
    if signature(s.Parser(result.decode('utf-8-sig')).documents())!=signature(expected):
        raise ValueError('v8unpack form handler changed XML-mapped properties')
    return result
