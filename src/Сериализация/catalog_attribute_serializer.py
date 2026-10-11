"""Append a variable string attribute to a Catalog, preserving existing forms."""
import base64,copy,hashlib,json,re,struct,sys,uuid,zlib
from pathlib import Path
from xml.etree import ElementTree as E
import metadata_serializer as s
import metadata_identifiers as ids
import platform_profiles as platforms
import constant_serializer as c


def serialize(request):
    if not platforms.legacy(request['platform']):raise ValueError('Catalog attributes require legacy platform profile')
    oid=c.guid(request['object_id']);name=request['name'];length=request['length']
    if not isinstance(name,str) or not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE):raise ValueError('Invalid attribute name')
    if type(length)!=int or not 1<=length<=1024:raise ValueError('String length must be 1..1024')
    for key in ('snapshot','context'):
        if not isinstance(request[key],str) or len(request[key])>s.MAX_BYTES*2:raise ValueError('Oversized attribute input')
    snapshot=base64.b64decode(request['snapshot'],validate=True);context=base64.b64decode(request['context'],validate=True)
    s.validate_storage(snapshot);s.validate_storage(context)
    rawmeta,pos=s.read_record(snapshot,12);data,pos=s.read_record(snapshot,pos)
    saved=s.Parser(rawmeta.decode('utf-8-sig')).documents();docs=s.context_metadata(context,oid);m=docs[0]
    if (len(docs)!=3 or len(saved)!=3 or len(m)!=17 or len(saved[0])!=17 or s.val(m[0])!='5'
            or s.val(saved[0][0])!='5' or [s.render(v) for v in m[:12]]!=[s.render(v) for v in saved[0][:12]]):raise ValueError('Snapshot/context mismatch')
    if s.val(m[2])!=ids.class_id('Catalog') or s.val(m[3])==s.ZERO or s.val(m[4])!=s.ZERO or s.render(m[11])!='{0}' or s.render(docs[2])!='{0}' or s.render(saved[2])!='{0}':raise ValueError('Unsupported Catalog metadata')
    pairs=c.children(m)
    if any(cls!=ids.class_id('CatalogForm') for child,cls in pairs):raise ValueError('Only forms are supported as existing children')
    if s.metadata_relations(m[14])!=s.metadata_relations(saved[0][14]):raise ValueError('Snapshot/context relations differ')
    features={s.val(v) for v in m[13][1:]}
    for group in (m[13],saved[0][13]):
        if int(s.val(group[0]))!=len(group)-1 or {s.val(v) for v in group[1:]}!=features or len(features)!=len(group)-1:raise ValueError('Invalid attribute feature map')
    original=request['original_version'].lower()
    if not re.fullmatch('[0-9a-f]{40}',original) or uuid.UUID(s.val(m[7])).bytes_le.hex()!=original[:32]:raise ValueError('Source version mismatch')
    raw=s.inflate(data);body=s.Parser(raw.decode('utf-8-sig')).documents()
    if len(body)!=1 or len(body[0])!=8 or len(body[0][1])!=61 or s.val(body[0][1][0])!='57':raise ValueError('Unsupported Catalog body')
    common=body[0][1][9][1]
    if s.val(common[1][2])!=oid or s.val(common[2])!=s.val(m[9]):raise ValueError('Catalog body/description mismatch')
    row=body[0][6]
    if s.val(row[0])!=ids.group_id('CatalogAttributes') or int(s.val(row[1]))!=len(row)-2:raise ValueError('Unsupported attribute collection')
    existing=[]
    for item in row[2:]:
        props=item[0][1][1][1];existing.append(c.guid(s.val(props[1][2])))
        if s.val(props[2]).casefold()==name.casefold():raise ValueError('Attribute name already exists')
    if set(existing)!=features or len(set(existing))!=len(existing):raise ValueError('Attribute collection/features mismatch')
    aid=str(uuid.uuid4());entry=s.Parser(json.loads(Path(__file__).with_name('catalog_attribute_layout_851.json').read_text(encoding='utf-8'))['template']).documents()[0]
    common=entry[0][1][1][1];common[1][2]=s.atom(aid);common[2]=s.atom(name,True)
    entry[0][1][1][2][1][1]=s.atom(length)
    updated=[row[0],s.atom(len(row)-1)]+list(row[2:])+[entry]
    text=raw.decode('utf-8-sig');new_raw=b'\xef\xbb\xbf'+(text[:row.start]+s.render(updated)+text[row.end:]).encode('utf-8');compressed=s.compress(new_raw)
    local=uuid.uuid4().bytes_le+struct.pack('<I',zlib.crc32(new_raw));a=s.atom
    m[0],m[5],m[6],m[7],m[8]=a(6),a(4294967295),a(0),a(base64.b64encode(bytes.fromhex(original)).decode()),a(base64.b64encode(local).decode())
    m[13]=[a(len(existing)+1)]+[a(v) for v in existing]+[a(aid)]
    relations=s.metadata_relations(m[14]);relations.update({child:1 for child,cls in pairs})
    m[14]=[a(len(relations))]+[a(v) for v in relations]+[a(v) for v in relations.values()]
    m[15:17]=copy.deepcopy(saved[0][15:17]);docs[1]=copy.deepcopy(saved[1]);meta=s.text_bytes(docs)
    manifest=s.text_bytes([[a(0),a(1),a(oid),a(hashlib.sha1(meta).hexdigest(),True),a(hashlib.sha1(compressed).hexdigest(),True),a(0)]])
    storage=s.storage([meta,compressed],manifest);s.validate_storage(storage)
    childmap=[a(len(pairs))]
    for child,cls in pairs:childmap.extend([a(child),a(cls)])
    graph=[[a(1),a(oid),c.descriptor(m)],[a(1),[a(oid)]+m[13]],[a(1),s.graph_relations(oid,m[14])],
        [a(1),a(oid),m[3]],[a(1),a(oid),a(1)],[a(1),a(oid),childmap],[a(0)],
        [a(1),a(oid),[a(0)]],[a(1),a(oid),a(1)],[a(1),a(oid),a(1)],a(0),[a(0)],a(0),[a(0)],[a(1),[a(0)]]]
    payload=s.SERIALIZER+s.compress(s.record(s.text_bytes([graph]))+bytes(4)+s.record(storage))
    E.register_namespace('crs',s.NS);call=E.Element('{%s}call'%s.NS,alias=request['repository'],name='DevDepot_commitObjects',version=request['platform'])
    def field(parent,key,value=None,text=None):
        n=E.SubElement(parent,'{%s}%s'%(s.NS,key));n.text=text
        if value is not None:n.set('value',str(value))
        return n
    p=field(call,'params');field(p,'clientVerID',c.guid(request['repository_version']));field(p,'data',text=base64.b64encode(payload).decode())
    for section in ('requested','changes'):
        v=field(field(p,section),'value');field(v,'first',oid);second=field(v,'second');detail=field(second,'_super') if section=='changes' else second
        supernode=field(detail,'_super');field(supernode,'id',oid);field(supernode,'classID',s.val(m[2]))
        for key,index in [('name',9),('pos',10),('parentID',3),('ownerID',4)]:field(detail,key,s.val(m[index]))
        field(detail,'verNum',-1);field(detail,'selfVerNum',0);version=field(detail,'version');field(version,'original',original);field(version,'local',local.hex());field(detail,'removed','false')
        if section=='changes':field(second,'externals')
    field(p,'objectsToRemove');field(p,'code','');field(p,'comment',text='');field(p,'features')
    return dict(request_xml=E.tostring(call,encoding='unicode'),attribute_id=aid)


def main():
    try:result=dict(ok=True,**serialize(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))))
    except (ValueError,KeyError,IndexError,TypeError,zlib.error) as error:result=dict(ok=False,error=str(error))
    Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')


if __name__=='__main__':main()
