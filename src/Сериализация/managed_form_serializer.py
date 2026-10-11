"""Shared native builder for verified managed forms and their parent maps."""
import base64
import copy
import hashlib
import json
import re
import struct
import sys
import uuid
import zlib
from pathlib import Path
import metadata_serializer as s
import constant_serializer as c
import metadata_identifiers as identifiers
import platform_profiles as platforms


def serialize(request):
    kind=request.get('form_kind','Catalog')
    if kind not in ('Catalog','Document','CommonForm'):raise ValueError('Unsupported managed form kind')
    parent_kind='Configuration' if kind=='CommonForm' else kind
    cls=identifiers.class_id('CommonForm' if kind=='CommonForm' else kind+'Form')
    if not platforms.legacy(request['platform']):raise ValueError('Managed forms require legacy platform profile')
    oid=c.guid(request['object_id']); name=request['name']
    if not isinstance(name,str) or not re.fullmatch(r'[^\W\d]\w{0,79}',name,re.UNICODE):raise ValueError('Invalid form name')
    for key in ('snapshot','context'):
        if not isinstance(request[key],str) or len(request[key])>s.MAX_BYTES*2:raise ValueError('Oversized form input')
    snapshot=base64.b64decode(request['snapshot'],validate=True);context=base64.b64decode(request['context'],validate=True)
    s.validate_storage(snapshot);s.validate_storage(context)
    meta,pos=s.read_record(snapshot,12);data,pos=s.read_record(snapshot,pos)
    saved=s.Parser(meta.decode('utf-8-sig')).documents();docs=s.context_metadata(context,oid);m=docs[0]
    if (len(saved)!=3 or len(docs)!=3 or len(m)!=17 or len(saved[0])!=17
            or s.val(m[0])!='5' or s.val(saved[0][0])!='5'
            or [s.render(v) for v in m[:12]]!=[s.render(v) for v in saved[0][:12]]):
        raise ValueError('Form parent snapshot/context mismatch')
    if ((s.render(saved[0][12])!="{0}" and sorted(c.children(m))!=sorted(c.children(saved[0]))) or s.metadata_relations(m[14])!=s.metadata_relations(saved[0][14])
            or {s.val(v) for v in m[13][1:]}!={s.val(v) for v in saved[0][13][1:]}):raise ValueError('Parent snapshot/context maps differ')
    for features in (m[13],saved[0][13]):
        if int(s.val(features[0]))!=len(features)-1 or len({s.val(v) for v in features[1:]})!=len(features)-1:raise ValueError('Invalid parent features')
    if (s.val(m[2])!=identifiers.class_id(parent_kind) or s.val(m[4])!=s.ZERO
            or s.render(m[11])!='{0}' or s.render(docs[2])!='{0}' or s.render(saved[2])!='{0}'):
        raise ValueError('Unsupported form parent or external data')
    if kind!='CommonForm' and (s.val(m[3])==s.ZERO or s.render(m[13])!='{0}' or s.metadata_relations(m[14])!={s.val(m[3]):1}):raise ValueError('Invalid object parent relations')
    if kind=='CommonForm' and s.val(m[3])!=s.ZERO:raise ValueError('Expected Configuration root')
    pairs=c.children(m)
    if kind!='CommonForm' and any(v!=cls for _,v in pairs):raise ValueError('Only existing forms are supported as children')
    all_context=c.context_objects(request['context'])
    for child,child_class in pairs:
        if child not in all_context or s.val(all_context[child][0][2])!=child_class or s.val(all_context[child][0][3])!=oid:raise ValueError('Invalid existing child context')
        if child_class==cls and s.val(all_context[child][0][9]).casefold()==name.casefold():raise ValueError('Form name already exists')
    original=request['original_version'].lower()
    if not re.fullmatch('[0-9a-f]{40}',original) or uuid.UUID(s.val(m[7])).bytes_le.hex()!=original[:32]:
        raise ValueError('Source parent version mismatch')
    raw=s.inflate(data);body=s.Parser(raw.decode('utf-8-sig')).documents()
    if kind=='CommonForm':s.common_properties(body,oid,request['platform']);object_type=''
    else:
        if len(body)!=1 or len(body[0])!=8 or len(body[0][1])!=(61 if kind=='Catalog' else 53) or s.val(body[0][1][0])!=('57' if kind=='Catalog' else '40'):raise ValueError('Unsupported form owner layout')
        common=body[0][1][9][1]
        if s.val(common[1][2])!=oid or s.val(common[2])!=s.val(m[9]):raise ValueError('Owner body/description mismatch')
        if kind=='Catalog' and (s.val(body[0][1][17])!='9' or s.val(body[0][1][19])!='25' or s.val(body[0][1][18])!='1'):raise ValueError('Only the verified default Catalog attributes are supported')
        if kind=='Document' and s.val(body[0][1][12])!='9':raise ValueError('Only the verified Document number is supported')
        object_type=c.guid(s.val(body[0][1][1]))
    rows=[]
    def walk(node):
        if isinstance(node,list):
            if len(node)>=2 and not isinstance(node[0],list) and s.val(node[0])==cls:rows.append(node)
            for child in node:walk(child)
    walk(body)
    expected={child for child,child_class in pairs if child_class==cls}
    if len(rows)!=1 or int(s.val(rows[0][1]))!=len(rows[0])-2 or {s.val(v) for v in rows[0][2:]}!=expected or len(expected)!=len(rows[0])-2:raise ValueError('Form collection/context mismatch')
    fid=str(uuid.uuid4());a=s.atom
    row=rows[0];changed=[row[0],a(len(row)-1)]+list(row[2:])+[a(fid)]
    text=raw.decode('utf-8-sig');new_raw=b'\xef\xbb\xbf'+(text[:row.start]+s.render(changed)+text[row.end:]).encode('utf-8')
    layout=json.loads(Path(__file__).with_name({'Catalog':'catalog_form_layout_851.json','Document':'document_form_layout_851.json','CommonForm':'common_form_layout_851.json'}[kind]).read_text(encoding='utf-8'))
    form=s.Parser(layout['body_template']).documents();form_common=form[0][1][1][1]
    form_common[1][2]=a(fid);form_common[2]=a(name,True)
    form_raw=s.native_body_bytes(form)
    external=b'\xef\xbb\xbf'+layout['external_template'].replace('${catalog_object_type}',object_type).replace('\r\n','\n').replace('\n','\r\n').encode('utf-8')
    s.Parser(external.decode('utf-8-sig')).documents()
    ver=lambda raw:uuid.uuid4().bytes_le+struct.pack('<I',zlib.crc32(raw))
    versions={oid:ver(new_raw),fid:ver(form_raw)};originals={oid:bytes.fromhex(original),fid:versions[fid]}
    external_version=uuid.uuid4().bytes_le+bytes(4);external64=base64.b64encode(external_version).decode();external_name=fid+'.0'
    m[0],m[5],m[6]=a(6),a(4294967295),a(0)
    m[7],m[8]=a(base64.b64encode(originals[oid]).decode()),a(base64.b64encode(versions[oid]).decode())
    class_row=next((v for v in m[12][1:] if s.val(v[0])==cls),None)
    if class_row is None:m[12][0]=a(len(m[12]));m[12].append([a(cls),a(1),a(fid)])
    else:class_row[1]=a(len(class_row)-1);class_row.append(a(fid))
    if kind=='CommonForm':
        count=int(s.val(m[14][0]));m[14]=[a(count+1)]+list(m[14][1:1+count])+[a(fid)]+list(m[14][1+count:])+[a(1)]
    m[15:17]=copy.deepcopy(saved[0][15:17]);docs[1]=copy.deepcopy(saved[1])
    form64=base64.b64encode(versions[fid]).decode()
    fm=[a(6),a(fid),a(cls),a(oid),a(s.ZERO),a(4294967295),a(0),a(form64),a(form64),a(name,True),a(len(expected)),
        [a(1),a(external_name,True),a(external64)],[a(0)],[a(0)],[a(1),a(oid),a(1)],
        a((s.val(m[15]) if kind!='CommonForm' else '')+cls+'.'+name,True),a(0)]
    fd=[fm,copy.deepcopy(saved[1]),[a(1),[a(external_name,True),a(external64),a(0)]]]
    objects={oid:docs,fid:fd};desc={v:c.descriptor(d[0]) for v,d in objects.items()}
    child_map=[a(len(pairs)+1)]
    for child,child_class in pairs+[(fid,cls)]:child_map.extend([a(child),a(child_class)])
    graph=[[a(2),a(oid),desc[oid],a(fid),desc[fid]],[a(1),[a(oid)]+copy.deepcopy(m[13])],
        [a(2),s.graph_relations(fid,fm[14]),s.graph_relations(oid,m[14])],
        [a(2),a(oid),m[3],a(fid),a(oid)],[a(2),a(oid),a(1),a(fid),a(1)],
        [a(1),a(oid),child_map],[a(1),a(fid),[a(1),a(fid),desc[fid]]],
        [a(2),a(fid),fm[11],a(oid),[a(0)]],[a(2),a(oid),a(1),a(fid),a(1)],
        [a(2),a(oid),a(1),a(fid),a(1)],a(0),[a(0)],a(0),[a(0)],[a(1),[a(0)]]]
    records=[];manifest=[a(0),a(2)]
    for key,value in ((fid,form_raw),(oid,new_raw)):
        meta=s.text_bytes(objects[key]);compressed=s.compress(value);records.extend([meta,compressed])
        manifest.extend([a(key),a(hashlib.sha1(meta).hexdigest(),True),a(hashlib.sha1(compressed).hexdigest(),True),a(1 if key==fid else 0)])
        if key==fid:
            extra=s.compress(external);records.append(extra);manifest.extend([a(external_name,True),a(hashlib.sha1(extra).hexdigest(),True)])
    storage=s.storage(records,s.text_bytes([manifest]));s.validate_storage(storage)
    payload=s.SERIALIZER+s.compress(s.record(s.text_bytes([graph]))+bytes(4)+s.record(storage))
    descriptions=[]
    for key in (fid,oid):
        mm=objects[key][0];descriptions.append(dict(id=key,class_id=s.val(mm[2]),name=s.val(mm[9]),pos=int(s.val(mm[10])),
            parent_id=s.val(mm[3]),owner_id=s.val(mm[4]),original=originals[key].hex(),local=versions[key].hex()))
    return dict(object_id=fid,data=base64.b64encode(payload).decode(),version_code='',descriptions=descriptions,
        externals=[dict(object_id=fid,name=external_name,version=external_version.hex(),action=0)])


def main():
    try:result=dict(ok=True,**serialize(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))))
    except (ValueError,KeyError,IndexError,TypeError,zlib.error) as error:result=dict(ok=False,error=str(error))
    Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')


if __name__=='__main__':main()
