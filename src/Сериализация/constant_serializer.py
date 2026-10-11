"""Experimental flat Configuration + string Constant creation, 8.5.4.1878.

Input is fresh server snapshots/context and Constant XML. No capture, CF, network
or Designer is used. Native layout is deliberately limited to verified defaults.
"""
import base64
import copy
import hashlib
import json
import re
import struct
import sys
import uuid
import xml.etree.ElementTree as E
import zlib
import comment_serializer as s
import metadata_identifiers as identifiers

CLASS = identifiers.class_id('Constant')
LANGUAGE = identifiers.class_id('Language')
MD = 'http://v8.1c.ru/8.3/MDClasses'
CORE = 'http://v8.1c.ru/8.1/data/core'
READABLE = 'http://v8.1c.ru/8.3/xcf/readable'
# Verified native layout for a string constant with default editing/choice/history.
TEMPLATE = ('{1,{16,{27,{2,{4,{1,0,00000000-0000-0000-0000-000000000000},"",'
            '{0},"",0,0,00000000-0000-0000-0000-000000000000,0,0,3},'
            '{"Pattern",{"S",100,1}}},0,{0},{0},0,"",0,{"U"},{"U"},0,'
            '00000000-0000-0000-0000-000000000000,2,0,{5006,0},{3,0,0},{0,0},0,'
            '{0},{"S",""},0,0,0},'
            '00000000-0000-0000-0000-000000000000,00000000-0000-0000-0000-000000000000,'
            '00000000-0000-0000-0000-000000000000,00000000-0000-0000-0000-000000000000,'
            '1,1,{0},{0},00000000-0000-0000-0000-000000000000,0,0,'
            '00000000-0000-0000-0000-000000000000,00000000-0000-0000-0000-000000000000,0,0},0}')
DEFAULTS = {
    'UseStandardCommands':'true','DefaultForm':'','ExtendedPresentation':'','Explanation':'',
    'PasswordMode':'false','Format':'','EditFormat':'','ToolTip':'','MarkNegatives':'false',
    'Mask':'','MultiLine':'false','ExtendedEdit':'false','MinValue':'','MaxValue':'',
    'FillChecking':'DontCheck','ChoiceFoldersAndItems':'Items','ChoiceParameterLinks':'',
    'ChoiceParameters':'','QuickChoice':'Auto','ChoiceForm':'','LinkByType':'',
    'ChoiceHistoryOnInput':'Auto','DataLockControlMode':'Managed','DataHistory':'DontUse',
    'UpdateDataHistoryImmediatelyAfterWrite':'false','ExecuteAfterWriteDataHistoryVersionProcessing':'false'}

def guid(value):
    result = str(uuid.UUID(value))
    if result == s.ZERO:
        raise ValueError('Zero UUID is forbidden')
    return result

def context_objects(encoded):
    if not isinstance(encoded,str) or len(encoded)>s.MAX_BYTES*2:
        raise ValueError('Oversized or invalid context')
    data = base64.b64decode(encoded, validate=True)
    s.validate_storage(data)
    pos, objects = 12, {}
    while pos < len(data):
        raw, pos = s.read_record(data, pos)
        if not raw.startswith(b'\xef\xbb\xbf{5,'):
            break
        docs = s.Parser(raw.decode('utf-8-sig')).documents()
        m = docs[0]
        if len(docs) != 3 or len(m) != 17 or s.val(m[0]) != '5':
            raise ValueError('Unsupported context metadata')
        oid = guid(s.val(m[1]))
        if oid in objects:
            raise ValueError('Duplicate context UUID')
        objects[oid] = docs
    return objects

def children(metadata):
    result = []
    group = metadata[12]
    if int(s.val(group[0])) != len(group)-1:
        raise ValueError('Invalid child class map')
    for row in group[1:]:
        if int(s.val(row[1])) != len(row)-2:
            raise ValueError('Invalid child class count')
        result.extend((guid(s.val(oid)), s.val(row[0])) for oid in row[2:])
    if len({oid for oid, _ in result}) != len(result):
        raise ValueError('Duplicate child UUID')
    return result

def inspect(request):
    objects = context_objects(request['context'])
    oid = guid(request['object_id'])
    m = objects[oid][0]
    if s.val(m[2]) != s.ROOT_CLASS or s.val(m[3]) != s.ZERO:
        raise ValueError('Configuration root required')
    return [child for child, cls in children(m)]

def constant_xml(text):
    if not isinstance(text, str) or len(text.encode('utf-8')) > s.MAX_BYTES:
        raise ValueError('Oversized Constant XML')
    if '<!DOCTYPE' in text.upper():raise ValueError('DOCTYPE is unsupported')
    top = E.fromstring(text)
    if top.tag != '{%s}MetaDataObject'%MD or len(top) != 1 or top[0].tag != '{%s}Constant'%MD:
        raise ValueError('Expected MetaDataObject/Constant XML')
    if top.attrib not in ({},{'version':'2.22'}):raise ValueError('Unsupported XML version or attributes')
    constant = top[0]; oid = guid(constant.attrib['uuid'])
    if constant.attrib != {'uuid':constant.attrib['uuid']}:raise ValueError('Unsupported Constant attributes')
    if len({n.tag for n in constant}) != len(constant):
        raise ValueError('Duplicate Constant XML section')
    if any(n.tag not in ('{%s}Properties'%MD,'{%s}InternalInfo'%MD) for n in constant):
        raise ValueError('Unsupported Constant XML section')
    props = constant.find('{%s}Properties'%MD)
    if props is None or len({n.tag for n in props}) != len(props):
        raise ValueError('Missing or duplicate Constant properties')
    if props.attrib:raise ValueError('Unsupported Properties attributes')
    fields = {n.tag.removeprefix('{%s}'%MD):n for n in props}
    if any(n.tag != '{%s}%s'%(MD,key) for key,n in fields.items()):
        raise ValueError('Unexpected property namespace')
    def value(key):return fields[key].text or ''
    name = value('Name')
    if not re.fullmatch(r'[^\W\d]\w{0,79}',name, re.UNICODE):
        raise ValueError('Invalid Constant name')
    for key,node in fields.items():
        if key in ('Name','Comment','Synonym','Type'):continue
        if key not in DEFAULTS or (node.text or '') != DEFAULTS[key] or len(node):
            raise ValueError('Unsupported Constant property: '+key)
        permitted = {'{http://www.w3.org/2001/XMLSchema-instance}nil':'true'} if key in ('MinValue','MaxValue') else {}
        if node.attrib and node.attrib != permitted:
            raise ValueError('Unsupported property attributes: '+key)
    for key in ('Name','Comment'):
        if key in fields and (len(fields[key]) or fields[key].attrib):
            raise ValueError('Invalid text property')
    synonyms = []
    if 'Synonym' in fields:
        if fields['Synonym'].attrib:raise ValueError('Unsupported Synonym attributes')
        for item in fields['Synonym']:
            if item.tag != '{%s}item'%CORE or [n.tag for n in item] != ['{%s}lang'%CORE,'{%s}content'%CORE]:
                raise ValueError('Unsupported Synonym')
            if item.attrib or any(n.attrib or len(n) for n in item):raise ValueError('Unsupported Synonym structure')
            lang, content = (n.text or '' for n in item)
            if not re.fullmatch('[a-zA-Z][a-zA-Z0-9_-]*',lang) or lang in [pair[0] for pair in synonyms]:
                raise ValueError('Invalid or duplicate Synonym language')
            synonyms.append((lang,content))
    typ = fields['Type']
    if [n.tag for n in typ] != ['{%s}Type'%CORE,'{%s}StringQualifiers'%CORE] or typ[0].text != 'xs:string':
        raise ValueError('Only String type is supported')
    qualifiers = typ[1]
    if typ.attrib or qualifiers.attrib or typ[0].attrib or len(typ[0]) or any(n.attrib or len(n) for n in qualifiers):
        raise ValueError('Unsupported Type structure')
    if [n.tag for n in qualifiers] != ['{%s}Length'%CORE,'{%s}AllowedLength'%CORE]:
        raise ValueError('Unsupported string qualifiers')
    length = int(qualifiers[0].text)
    if not 1 <= length <= 1024 or qualifiers[1].text != 'Variable':
        raise ValueError('Only variable strings of length 1..1024 are supported')
    docs = s.Parser(TEMPLATE).documents();native = docs[0][1];common = native[1][1][1]
    common[1][2],common[2],common[4] = s.atom(oid),s.atom(name,True),s.atom(value('Comment') if 'Comment' in fields else '',True)
    common[3] = [s.atom(len(synonyms))]
    for lang,content in synonyms:common[3].extend([s.atom(lang,True),s.atom(content,True)])
    native[1][1][2][1][1] = s.atom(length)
    internal = constant.find('{%s}InternalInfo'%MD)
    ids=[]
    if internal is not None:
        expected = [('ConstantManager.','Manager'),('ConstantValueManager.','ValueManager'),('ConstantValueKey.','ValueKey')]
        if len(internal)!=3 or internal.attrib:raise ValueError('Expected three generated types')
        for node,(prefix,category) in zip(internal,expected):
            if node.tag != '{%s}GeneratedType'%READABLE or node.attrib != {'name':prefix+name,'category':category} or [n.tag for n in node] != ['{%s}TypeId'%READABLE,'{%s}ValueId'%READABLE]:
                raise ValueError('Unsupported generated type')
            ids.extend(guid(n.text) for n in node)
            if any(n.attrib or len(n) for n in node):raise ValueError('Unsupported generated UUID structure')
    else:ids=[str(uuid.uuid4()) for _ in range(6)]
    if len(set(ids+[oid]))!=7:raise ValueError('Duplicate generated UUID')
    for index,value_ in zip((2,3,4,5,13,14),ids):native[index]=s.atom(value_)
    return oid,name,s.native_body_bytes(docs),ids

def descriptor(m):
    return [m[1],m[2],m[3],m[9],m[10],m[5],m[6],m[3],m[4],m[7],m[8],s.atom(0)]

def serialize(request):
    if request['platform']!='8.5.4.1878':raise ValueError('Only platform 8.5.4.1878 is supported')
    rid=guid(request['object_id']);objects=context_objects(request['context']);root=objects[rid]
    inspect(request)
    oldchildren=children(root[0]);expected={rid}|{oid for oid,_ in oldchildren}
    if any(cls not in (CLASS,LANGUAGE) for _,cls in oldchildren):
        raise ValueError('Only a flat Configuration with Languages and Constants is supported')
    if set(request['snapshots'])!=expected:raise ValueError('Snapshots must cover root and all existing children')
    if any(not isinstance(v,str) for v in request['snapshots'].values()) or sum(len(v) for v in request['snapshots'].values())>s.MAX_BYTES*2:
        raise ValueError('Oversized or invalid snapshots')
    cid,name,body,generated=constant_xml(request['constant_xml'])
    if cid in objects or any(s.val(objects[oid][0][9]).casefold()==name.casefold() for oid,cls in oldchildren if cls==CLASS):
        raise ValueError('Constant UUID or name already exists')
    known=set(objects)
    if any(g in known for g in generated):raise ValueError('Generated type UUID collides with an object')
    raws={};versions={};originals={}
    for oid in sorted(expected):
        data=base64.b64decode(request['snapshots'][oid],validate=True);s.validate_storage(data)
        meta,pos=s.read_record(data,12);content,pos=s.read_record(data,pos)
        saved=s.Parser(meta.decode('utf-8-sig')).documents()[0];m=objects[oid][0]
        if [s.render(saved[i]) for i in range(12)] != [s.render(m[i]) for i in range(12)]:
            raise ValueError('Snapshot/context mismatch')
        for features in (saved[13],m[13]):
            if int(s.val(features[0]))!=len(features)-1 or len({s.val(v) for v in features[1:]})!=len(features)-1:
                raise ValueError('Invalid metadata features')
        if {s.val(v) for v in saved[13][1:]}!={s.val(v) for v in m[13][1:]} or s.metadata_relations(saved[14])!=s.metadata_relations(m[14]):
            raise ValueError('Snapshot/context relations or features mismatch')
        m[15:17]=copy.deepcopy(saved[15:17])
        if s.render(m[11])!='{0}' or s.render(objects[oid][2])!='{0}' or (oid!=rid and children(m)):
            raise ValueError('Nested or external object data is unsupported')
        if oid!=rid and s.val(m[3])!=rid:raise ValueError('Invalid child parent')
        if s.val(m[4])!=s.ZERO:raise ValueError('Owned objects unsupported')
        originals[oid]=uuid.UUID(s.val(m[7])).bytes_le+bytes(4)
        raws[oid]=s.inflate(content)
        versions[oid]=uuid.UUID(s.val(m[8])).bytes_le+struct.pack('<I',zlib.crc32(raws[oid]))
    for metadata in objects.values():known.update(re.findall(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', s.render(metadata).lower()))
    for raw in raws.values():known.update(re.findall(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',raw.decode('utf-8-sig').lower()))
    if any(g in known for g in generated+[cid]):raise ValueError('New UUID collides with existing native data')
    text=raws[rid].decode('utf-8-sig');docs=s.Parser(text).documents()
    matches=[]
    def walk(node):
        if isinstance(node,list):
            if len(node)>=2 and not isinstance(node[0],list) and s.val(node[0])==CLASS:
                matches.append(node)
            for sub in node:walk(sub)
    walk(docs)
    if len(matches)!=1:raise ValueError('Constant class map not found uniquely in root')
    row=matches[0]
    if {s.val(v) for v in row[2:]}!={oid for oid,cls in oldchildren if cls==CLASS} or int(s.val(row[1]))!=len(row)-2 or len({s.val(v) for v in row[2:]})!=len(row)-2:
        raise ValueError('Root content/context Constant map differs')
    updated=[row[0],s.atom(len(row)-1)]+list(row[2:])+[s.atom(cid)]
    # Positions follow the native collection order, not the context-map order.
    # Earlier packages assigned position 0 to every newly created Constant.
    # Designer normalizes these duplicate positions on retrieval.
    constant_positions={s.val(node):index for index,node in enumerate(updated[2:])}
    # Existing descriptors must stay identical to their source descriptions.
    # Previously stored duplicate positions require a separate native repair.
    raws[rid]=b'\xef\xbb\xbf'+(text[:row.start]+s.render(updated)+text[row.end:]).encode('utf-8')
    versions[rid]=uuid.uuid4().bytes_le+struct.pack('<I',zlib.crc32(raws[rid]))
    versions[cid]=uuid.uuid4().bytes_le+struct.pack('<I',zlib.crc32(body));originals[cid]=versions[cid];raws[cid]=body
    rm=root[0];rmap=rm[12];constrow=next((r for r in rmap[1:] if s.val(r[0])==CLASS),None)
    if constrow is None:rmap[0]=s.atom(len(rmap));rmap.append([s.atom(CLASS),s.atom(1),s.atom(cid)])
    else:constrow[1]=s.atom(len(constrow)-1);constrow.append(s.atom(cid))
    # Native relation arrays are column-wise: all UUIDs, then all flags.
    count=int(s.val(rm[14][0]));relationids=list(rm[14][1:1+count]);flags=list(rm[14][1+count:])
    if len(flags)!=count or {s.val(n) for n in relationids}!={oid for oid,_ in oldchildren}:
        raise ValueError('Invalid root relation columns')
    rm[14]=[s.atom(count+1)]+relationids+[s.atom(cid)]+flags+[s.atom(1)]
    original64=base64.b64encode(originals[cid]).decode()
    cm=[s.atom(6),s.atom(cid),s.atom(CLASS),s.atom(rid),s.atom(s.ZERO),s.atom(4294967295),s.atom(0),s.atom(original64),s.atom(original64),s.atom(name,True),s.atom(constant_positions[cid]),[s.atom(0)],[s.atom(0)],[s.atom(0)],[s.atom(1),s.atom(rid),s.atom(1)],s.atom(CLASS+'.'+name,True),s.atom(0)]
    objects[cid]=[cm,copy.deepcopy(root[1]),[s.atom(0)]]
    order=[cid,rid]+[oid for oid,_ in oldchildren]
    for oid in order:
        m=objects[oid][0];m[0]=s.atom(6);m[5]=s.atom(4294967295);m[6]=s.atom(0)
        m[7]=s.atom(base64.b64encode(originals[oid]).decode());m[8]=s.atom(base64.b64encode(versions[oid]).decode())
    desc={oid:descriptor(objects[oid][0]) for oid in order}
    a=s.atom
    graph=[[a(2),a(rid),desc[rid],a(cid),desc[cid]],
           [a(len(order)-1)]+[[a(oid)]+objects[oid][0][13] for oid in order if oid!=cid],
           [a(len(order))]+[s.graph_relations(oid,objects[oid][0][14]) for oid in [rid,cid]+[v for v in order if v not in (rid,cid)]],
           [a(2),a(rid),a(s.ZERO),a(cid),a(rid)],
           [a(len(order))], [a(len(order)-1)],
           [a(2),a(cid),[a(1),a(cid),desc[cid]],a(rid),[a(len(order))]],
           [a(len(order))], [a(2),a(rid),a(1),a(cid),a(1)],
           [a(1),a(rid),a(1)],a(0),[a(0)],a(0),[a(0)],[a(1),[a(0)]]]
    for oid in [rid,cid]+[v for v in order if v not in (rid,cid)]:graph[4].extend([a(oid),a(1)])
    for oid in [rid]+[v for v in order if v not in (rid,cid)]:
        pairs=children(objects[oid][0]);childmap=[a(len(pairs))]
        for child,cls in sorted(pairs):childmap.extend([a(child),a(cls)])
        graph[5].extend([a(oid),childmap])
    for oid in [rid]+[v for v in order if v not in (rid,cid)]+[cid]:graph[6][-1].extend([a(oid),desc[oid]])
    for oid in order:graph[7].extend([a(oid),[a(0)]])
    records=[];manifest=[a(0),a(len(order))]
    for oid in order:
        meta=s.text_bytes(objects[oid]);data=s.compress(raws[oid]);records.extend([meta,data])
        manifest.extend([a(oid),a(hashlib.sha1(meta).hexdigest(),True),a(hashlib.sha1(data).hexdigest(),True),a(0)])
    snapshot=s.storage(records,s.text_bytes([manifest]));s.validate_storage(snapshot)
    payload=s.SERIALIZER+s.compress(s.record(s.text_bytes([graph]))+bytes(4)+s.record(snapshot))
    E.register_namespace('crs',s.NS)
    call=E.Element('{%s}call'%s.NS,alias=request['repository'],name='DevDepot_commitObjects',version=request['platform'])
    def field(parent,key,value=None,text=None):
        node=E.SubElement(parent,'{%s}%s'%(s.NS,key));node.text=text
        if value is not None:node.set('value',str(value))
        return node
    p=field(call,'params');field(p,'clientVerID',guid(request['repository_version']));field(p,'data',text=base64.b64encode(payload).decode())
    for section in ('requested','changes'):
        container=field(p,section)
        for oid in order:
            m=objects[oid][0];entry=field(container,'value');field(entry,'first',oid);second=field(entry,'second')
            detail=field(second,'_super') if section=='changes' else second
            supernode=field(detail,'_super');field(supernode,'id',oid);field(supernode,'classID',s.val(m[2]))
            for key,index in [('name',9),('pos',10)]:field(detail,key,s.val(m[index]))
            field(detail,'verNum',-1);field(detail,'selfVerNum',0)
            for key,index in [('parentID',3),('ownerID',4)]:field(detail,key,s.val(m[index]))
            ver=field(detail,'version');field(ver,'original',originals[oid].hex());field(ver,'local',versions[oid].hex());field(detail,'removed','false')
            if section=='changes':field(second,'externals')
    field(p,'objectsToRemove');field(p,'code',s.val(s.configuration_properties(docs)[15]));field(p,'comment',text='')
    feature=field(field(p,'features'),'value');field(feature,'first',rid)
    field(field(feature,'second'),'value',identifiers.feature_id('ConstantCollectionChanged'))
    descriptions=[]
    for oid in order:
        m=objects[oid][0]
        descriptions.append(dict(id=oid,class_id=s.val(m[2]),name=s.val(m[9]),pos=int(s.val(m[10])),
                                 parent_id=s.val(m[3]),owner_id=s.val(m[4]),
                                 original=originals[oid].hex(),local=versions[oid].hex()))
    return dict(request_xml=E.tostring(call,encoding='unicode'),object_id=cid,name=name,
                descriptions=descriptions,data=base64.b64encode(payload).decode(),
                version_code=s.val(s.configuration_properties(docs)[15]),existing_objects=sorted(expected))

def main():
    from pathlib import Path
    try:
        request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
        result={'ok':True}
        result.update({'children':inspect(request)} if request.get('mode')=='inspect' else serialize(request))
    except (ValueError,KeyError,IndexError,TypeError,zlib.error,E.ParseError) as error:
        result={'ok':False,'error':str(error)}
    Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')

if __name__=='__main__':main()
