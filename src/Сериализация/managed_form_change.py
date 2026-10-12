"""Append a Catalog attribute input field to the current native managed form."""
import base64,json,re,sys,uuid,zlib
from pathlib import Path
import metadata_serializer as s
import metadata_identifiers as ids
import external_data
from commonmodule_serializer import pack_external_change
import platform_profiles as platforms


def serialize(request):
    if not platforms.legacy(request['platform']):raise ValueError('Managed form changes require legacy profile')
    oid=str(uuid.UUID(request['object_id']));attribute=request['attribute_name']
    if not isinstance(attribute,str) or not re.fullmatch(r'[^\W\d]\w{0,79}',attribute,re.UNICODE):raise ValueError('Invalid attribute name')
    for key in ('snapshot','context','storage'):
        if not isinstance(request[key],str) or len(request[key])>s.MAX_BYTES*2:raise ValueError('Oversized form input')
    snapshot=base64.b64decode(request['snapshot'],validate=True);context=base64.b64decode(request['context'],validate=True);storage=base64.b64decode(request['storage'],validate=True)
    s.validate_storage(snapshot);s.validate_storage(context)
    meta,pos=s.read_record(snapshot,12);data,pos=s.read_record(snapshot,pos);saved=s.Parser(meta.decode('utf-8-sig')).documents();docs=s.context_metadata(context,oid);m=docs[0]
    if len(docs)!=3 or len(saved)!=3 or len(m)!=17 or len(saved[0])!=17 or s.val(m[0])!='5' or [s.render(v) for v in m[:12]]!=[s.render(v) for v in saved[0][:12]]:raise ValueError('Form snapshot/context mismatch')
    if s.val(m[2])!=ids.class_id('CatalogForm') or s.val(m[4])!=s.ZERO or any(s.render(m[i])!='{0}' for i in (12,13)):raise ValueError('Unsupported form metadata')
    parent_id=s.val(m[3]);name=oid+'.0';refs=m[11]
    if s.metadata_relations(m[14])!={parent_id:1} or s.metadata_relations(saved[0][14])!={parent_id:1} or len(refs)!=3 or s.val(refs[1])!=name:raise ValueError('Unsupported form source stream or relations')
    original=request['original_version'].lower()
    if not re.fullmatch('[0-9a-f]{40}',original) or uuid.UUID(s.val(m[7])).bytes_le.hex()!=original[:32]:raise ValueError('Source version mismatch')
    current=external_data.extract(storage,oid);parent=external_data.extract(storage,parent_id)
    if (current['class_id']!=s.val(m[2]) or current['parent_id']!=parent_id or current['version_number']!=int(s.val(m[5]))
            or current['original']!=original[:32] or current['local']!=uuid.UUID(s.val(m[8])).bytes_le.hex()
            or parent['class_id']!=ids.class_id('Catalog') or len(current['externals'])!=1):raise ValueError('Version storage/snapshot mismatch')
    stream=current['externals'][0]
    if stream['name']!=name or stream['version']!=uuid.UUID(s.val(refs[2])).bytes_le.hex()+'00000000':raise ValueError('External source version mismatch')
    owner=s.Parser(s.inflate(base64.b64decode(parent['data'],validate=True)).decode('utf-8-sig')).documents()[0]
    attributes=owner[6]
    if s.val(attributes[0])!=ids.group_id('CatalogAttributes') or int(s.val(attributes[1]))!=len(attributes)-2:raise ValueError('Unsupported Catalog attributes')
    matches=[v for v in attributes[2:] if s.val(v[0][1][1][1][2])==attribute]
    if len(matches)!=1:raise ValueError('Attribute not found or ambiguous')
    aid=s.val(matches[0][0][1][1][1][1][2]);uuid.UUID(aid)
    pattern=matches[0][0][1][1][2]
    if len(pattern)!=2 or s.val(pattern[0])!='Pattern' or s.val(pattern[1][0])!='S':raise ValueError('Only string attributes are supported')
    raw=s.inflate(base64.b64decode(stream['data'],validate=True));form=s.Parser(raw.decode('utf-8-sig')).documents()[0]
    if len(form)!=10 or s.val(form[0])!='4' or s.val(form[1][0])!='59':raise ValueError('Unsupported managed interface layout')
    props=form[1];layout=json.loads(Path(__file__).with_name('managed_form_field_layout_851.json').read_text(encoding='utf-8'));candidates=[]
    # Native storage and Designer's exported CF use two verified header variants.
    for index in (23,25):
        if index>=len(props) or isinstance(props[index],list):continue
        count=int(s.val(props[index]));end=index+1+count*2
        if count<0 or count>256 or end>=len(props):continue
        if all(not isinstance(props[i],list) and s.val(props[i])==layout['element_type'] and isinstance(props[i+1],list) and s.val(props[i+1][0])=='48' for i in range(index+1,end,2)):candidates.append((index,count,end))
    if len(candidates)!=1:raise ValueError('Unsupported or ambiguous control collection')
    index,count,end=candidates[0];maximum=0
    for i in range(index+1,end,2):
        control=props[i+1];maximum=max(maximum,int(s.val(control[1][0])))
        if s.val(control[6])==attribute or aid in s.render(control[11]):raise ValueError('Field already exists')
    main=form[3]
    if s.val(main[1])!='1' or s.val(main[2][3])!='Object' or s.val(main[2][5][1][1])!=s.val(owner[1][1]):raise ValueError('Form main Object type mismatch')
    entry=s.Parser(layout['template']).documents()[0];entry[1][0]=s.atom(max(20,maximum+10));entry[11][2][1]=s.atom(aid)
    def rename(node):
        if isinstance(node,list):
            for i,v in enumerate(node):
                if isinstance(v,list):rename(v)
                elif v.quoted and s.val(v).startswith(layout['prototype_name']):node[i]=s.atom(attribute+s.val(v)[len(layout['prototype_name']):],True)
    rename(entry);props[index]=s.atom(count+1);props[end:end]=[s.atom(layout['element_type']),entry]
    external=s.native_body_bytes([form]);body=s.inflate(data)
    definition=s.Parser(body.decode('utf-8-sig')).documents()[0]
    common=definition[1][1][1]
    if s.val(common[1][2])!=oid or s.val(common[2])!=s.val(m[9]):raise ValueError('Form body/description mismatch')
    return pack_external_change(docs,saved,data,oid,name,original,body,s.compress(external))


def main():
    try:result=dict(ok=True,**serialize(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))))
    except (ValueError,KeyError,IndexError,TypeError,zlib.error) as error:result=dict(ok=False,error=str(error))
    Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')


if __name__=='__main__':main()
