"""Delete one CatalogForm and rebuild its Catalog from the complete target XML."""
import base64,copy,hashlib,json,re,struct,sys,uuid,zlib
from pathlib import Path
import metadata_serializer as s
import constant_serializer as c
import metadata_identifiers as ids
import catalog_object_xml
import platform_profiles as platforms


def serialize(request):
    if not platforms.legacy(request['platform']):raise ValueError('Form deletion requires the legacy profile')
    fid=c.guid(request['form_id']);objects=c.context_objects(request['context']);fm=objects[fid][0]
    if s.val(fm[2])!=ids.class_id('CatalogForm') or s.val(fm[4])!=s.ZERO or c.children(fm):raise ValueError('Expected an existing CatalogForm')
    parent=c.guid(s.val(fm[3]));docs=objects[parent];m=docs[0]
    if s.val(m[2])!=ids.class_id('Catalog') or s.render(m[11])!='{0}':raise ValueError('Expected a Catalog parent without external data')
    def snapshot(key,oid,original):
        encoded=request[key]
        if not isinstance(encoded,str) or len(encoded)>s.MAX_BYTES*2:raise ValueError('Oversized deletion snapshot')
        data=base64.b64decode(encoded,validate=True);s.validate_storage(data)
        meta,pos=s.read_record(data,12);body,_=s.read_record(data,pos);saved=s.Parser(meta.decode('utf-8-sig')).documents()
        if [s.render(v) for v in saved[0][:12]]!=[s.render(v) for v in objects[oid][0][:12]]:raise ValueError('Deletion snapshot/context mismatch')
        if not re.fullmatch('[0-9a-f]{40}',original) or uuid.UUID(s.val(saved[0][7])).bytes_le.hex()!=original[:32]:raise ValueError('Deletion source version mismatch')
        return saved,s.inflate(body)
    original=request['original_version'].lower();form_original=request['form_original_version'].lower()
    saved,raw=snapshot('snapshot',parent,original);snapshot('form_snapshot',fid,form_original)
    pairs=c.children(m)
    if (fid,ids.class_id('CatalogForm')) not in pairs or any(cls!=ids.class_id('CatalogForm') for _,cls in pairs):raise ValueError('Invalid Catalog form map')
    if s.metadata_relations(saved[0][14])!=s.metadata_relations(m[14]):raise ValueError('Parent relations differ')
    forms={s.val(objects[child][0][9]):child for child,cls in pairs}
    if len(forms)!=len(pairs):raise ValueError('Duplicate form names')
    source=s.Parser(raw.decode('utf-8-sig')).documents()[0]
    changed,features=catalog_object_xml.convert(request['object_xml'],request['platform'],source,forms,[fid])
    target=s.Parser(changed.decode('utf-8-sig')).documents()[0]
    if any(s.render(source[i])!=s.render(target[i]) for i in range(7)):raise ValueError('Deletion XML must preserve all other Catalog properties and attributes')
    old_relations=[s.graph_relations(oid,d[0][14]) for oid,d in objects.items()]
    a=s.atom;local=uuid.uuid4().bytes_le+struct.pack('<I',zlib.crc32(changed))
    m[0],m[5],m[6]=a(6),a(4294967295),a(0);m[7]=a(base64.b64encode(bytes.fromhex(original)).decode());m[8]=a(base64.b64encode(local).decode())
    row=next(v for v in m[12][1:] if s.val(v[0])==ids.class_id('CatalogForm'))
    if len(pairs)==1:
        m[12].remove(row);m[12][0]=a(len(m[12])-1)
    else:row[:]=[row[0],a(len(pairs)-1)]+[a(oid) for oid,cls in pairs if oid!=fid]
    m[15:17]=copy.deepcopy(saved[0][15:17]);docs[1]=copy.deepcopy(saved[1]);docs[2]=[a(0)]
    kept={oid:d for oid,d in objects.items() if oid!=fid}
    versions={};originals={}
    for oid,d in kept.items():
        mm=d[0]
        if oid==parent:originals[oid]=bytes.fromhex(original);versions[oid]=local
        else:
            originals[oid]=uuid.UUID(s.val(mm[7])).bytes_le+bytes(4);versions[oid]=uuid.UUID(s.val(mm[8])).bytes_le+bytes(4)
            mm[7]=a(base64.b64encode(originals[oid]).decode());mm[8]=a(base64.b64encode(versions[oid]).decode());mm[5]=a(4294967295);mm[6]=a(0)
    descriptors=[a(len(kept))]
    for oid,d in kept.items():descriptors.extend([a(oid),c.descriptor(d[0])])
    parents=[a(len(kept))];flags=[a(len(kept))];active=[a(len(objects))]
    for oid,d in kept.items():parents.extend([a(oid),d[0][3]]);flags.extend([a(oid),a(1)])
    for oid in objects:active.extend([a(oid),a(0 if oid==fid else 1)])
    childmap=[a(len(pairs)-1)]
    for oid,cls in pairs:
        if oid!=fid:childmap.extend([a(oid),a(cls)])
    graph=[descriptors,[a(1),[a(parent)]+copy.deepcopy(m[13])],[a(0)],parents,active,
        [a(1),a(parent),childmap],[a(0)],[a(1),a(parent),[a(0)]],flags,copy.deepcopy(flags),
        a(1),[a(len(old_relations))]+old_relations,a(0),[a(0)],[a(1),[a(0)]]]
    meta=s.text_bytes(docs);data=s.compress(changed)
    manifest=s.text_bytes([[a(0),a(1),a(parent),a(hashlib.sha1(meta).hexdigest(),True),a(hashlib.sha1(data).hexdigest(),True),a(0)]])
    storage=s.storage([meta,data],manifest);s.validate_storage(storage)
    payload=s.SERIALIZER+s.compress(s.record(s.text_bytes([graph]))+bytes(4)+s.record(storage))
    descriptions=[]
    for oid,d in kept.items():
        mm=d[0];descriptions.append(dict(id=oid,class_id=s.val(mm[2]),name=s.val(mm[9]),pos=int(s.val(mm[10])),
            parent_id=s.val(mm[3]),owner_id=s.val(mm[4]),original=originals[oid].hex(),local=versions[oid].hex()))
    return dict(data=base64.b64encode(payload).decode(),object_id=fid,parent_id=parent,descriptions=descriptions,version_code='',externals=[])


def main():
    try:result=dict(ok=True,**serialize(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))))
    except (ValueError,KeyError,IndexError,TypeError,zlib.error) as error:result=dict(ok=False,error=str(error))
    Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')


if __name__=='__main__':main()
