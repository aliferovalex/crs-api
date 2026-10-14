"""Delete a separately stored form or template from its owner's complete XML."""
import base64,copy,json,uuid
from pathlib import Path
from xml.etree import ElementTree as E
import metadata_serializer as s
import serialization_context as contexts
import packet_builder as packets
import constant_serializer as c
import metadata_identifiers as ids
import catalog_object_xml
import platform_profiles as platforms


def serialize(request):
    if not platforms.legacy(request['platform']):raise ValueError('Form deletion requires the legacy profile')
    fid=c.guid(request['form_id']);objects=c.context_objects(request['context']);fm=objects[fid][0]
    kind=ids.class_labels().get(s.val(fm[2]));parent_kind={'CatalogForm':'Catalog','DocumentForm':'Document','DataProcessorForm':'DataProcessor','ReportForm':'Report','CommonForm':'Configuration','CommonTemplate':'Configuration'}.get(kind)
    if kind=='Template':
        parent_kind=ids.class_labels().get(s.val(objects[s.val(fm[3])][0][2]))
        if parent_kind not in ('Catalog','Document','DataProcessor','Report'):raise ValueError('Unsupported Template parent')
    if parent_kind is None or s.val(fm[4])!=s.ZERO or c.children(fm):raise ValueError('Expected an existing managed form')
    parent=c.guid(s.val(fm[3]));docs=objects[parent];m=docs[0]
    if s.val(m[2])!=ids.class_id(parent_kind):raise ValueError('Expected the form parent')
    def snapshot(key,oid,original):
        frame=contexts.read(request,oid,'Oversized deletion snapshot','Deletion snapshot/context mismatch',snapshot_key=key)
        contexts.original_version(original,frame.metadata,'Deletion source version mismatch')
        return frame.saved,s.inflate(frame.data)
    original=request['original_version'].lower();form_original=request['form_original_version'].lower()
    saved,raw=snapshot('snapshot',parent,original);snapshot('form_snapshot',fid,form_original)
    packets.preserve_external_versions(copy.deepcopy(saved),parent)
    parent_externals=packets.preserve_external_versions(docs,parent)
    pairs=c.children(m)
    cls=ids.class_id(kind)
    if (fid,cls) not in pairs:raise ValueError('Invalid parent form map')
    if s.metadata_relations(saved[0][14])!=s.metadata_relations(m[14]):raise ValueError('Parent relations differ')
    forms={s.val(objects[child][0][9]):child for child,child_class in pairs if child_class==cls}
    if len(forms)!=sum(child_class==cls for child,child_class in pairs):raise ValueError('Duplicate form names')
    source=s.Parser(raw.decode('utf-8-sig')).documents()[0]
    if parent_kind=='Catalog':
        changed=delete_catalog_child(request,parent,fid,source,m,objects,kind)
    elif kind in ('DocumentForm','DataProcessorForm','ReportForm','Template'):
        import flat_object_serializer as flat,child_object_xml as children
        layout=json.loads(Path(__file__).with_name(parent_kind.lower()+'_layout_851.json').read_text(encoding='utf-8'))
        for profile in layout.get('reference_values',{}).values():
            node=source
            for slot in profile['path']:node=node[slot]
            if s.val(node)==fid:raise ValueError('Deleted '+('template' if kind=='Template' else 'form')+' is selected by an owner reference; clear it before deletion')
        actual,name,changed,_=flat.object_xml(request['object_xml'],request['platform'],parent_kind,objects)
        if actual!=parent or name!=s.val(m[9]):raise ValueError('Deletion parent XML identity differs')
        target=s.Parser(changed.decode('utf-8-sig')).documents()[0]
        children.validate(source,target,layout,m,objects,removed=[fid]);baseline=copy.deepcopy(target)
        for profile in layout['child_collections'].values():baseline[profile['slot']]=copy.deepcopy(source[profile['slot']])
        if s.render(baseline)!=s.render(source):raise ValueError('Deletion XML must preserve all other '+parent_kind+' properties and attributes')
    else:
        changed=delete_root_child(request,parent,fid,source,m,objects,kind)
    old_relations=[s.graph_relations(oid,d[0][14]) for oid,d in objects.items()]
    a=s.atom;local=packets.content_version(changed)
    packets.commit_metadata(m,bytes.fromhex(original),local)
    row=next(v for v in m[12][1:] if s.val(v[0])==cls)
    remaining=[oid for oid,child_class in pairs if child_class==cls and oid!=fid]
    if not remaining:
        m[12].remove(row);m[12][0]=a(len(m[12])-1)
    else:row[:]=[row[0],a(len(remaining))]+[a(oid) for oid in remaining]
    m[15:17]=copy.deepcopy(saved[0][15:17]);docs[1]=copy.deepcopy(saved[1]);docs[2]=[a(0)]
    kept={oid:d for oid,d in objects.items() if oid!=fid}
    versions={};originals={}
    for oid,d in kept.items():
        mm=d[0]
        if oid==parent:originals[oid]=bytes.fromhex(original);versions[oid]=local
        else:
            originals[oid]=uuid.UUID(s.val(mm[7])).bytes_le+bytes(4);versions[oid]=uuid.UUID(s.val(mm[8])).bytes_le+bytes(4)
            mm[7]=a(base64.b64encode(originals[oid]).decode());mm[8]=a(base64.b64encode(versions[oid]).decode());mm[5]=a(4294967295);mm[6]=a(0)
    graph=packets.deletion_graph(objects,kept,parent,fid,pairs,old_relations)
    payload=packets.assemble(graph,[packets.ObjectRecord(parent,s.text_bytes(docs),s.compress(changed))])
    descriptions=[packets.description(d[0],originals[oid],versions[oid]) for oid,d in kept.items()]
    return dict(data=base64.b64encode(payload).decode(),object_id=fid,parent_id=parent,descriptions=descriptions,version_code='',externals=[dict(object_id=parent,**stream) for stream in parent_externals])


def delete_catalog_child(request,parent,fid,source,metadata,objects,kind):
    import template_serializer
    row,pairs,expected=template_serializer.collection([source],metadata,objects)
    text=request['object_xml']
    if not isinstance(text,str) or len(text.encode('utf-8'))>s.MAX_BYTES or '<!DOCTYPE' in text.upper():raise ValueError('Invalid Catalog deletion XML')
    root=E.fromstring(text);q='{'+c.MD+'}';child=root[0].find(q+'ChildObjects')
    if child is None:raise ValueError('Deletion needs complete Catalog ChildObjects')
    names=[node.text for node in child if node.tag==q+'Template']
    wanted=[s.val(objects[s.val(key)][0][9]) for key in row[2:] if kind!='Template' or s.val(key)!=fid]
    if names!=wanted or any(node.attrib or len(node) for node in child if node.tag==q+'Template'):
        raise ValueError('Deletion XML must preserve remaining template order')
    for node in list(child):
        if node.tag==q+'Template':child.remove(node)
    baseline=copy.deepcopy(source);baseline[3]=[s.atom(ids.class_id('Template')),s.atom(0)]
    forms={s.val(objects[oid][0][9]):oid for oid,cls in pairs if cls==ids.class_id('CatalogForm')}
    removed=[fid] if kind=='CatalogForm' else []
    rebuilt,_=catalog_object_xml.convert(E.tostring(root,encoding='unicode'),request['platform'],baseline,forms,removed)
    target=s.Parser(rebuilt.decode('utf-8-sig')).documents()[0]
    before=copy.deepcopy(baseline);before[7]=copy.deepcopy(target[7])
    if s.render(target)!=s.render(before):raise ValueError('Deletion XML must preserve all other Catalog properties and attributes')
    remaining=[key for key in row[2:] if kind!='Template' or s.val(key)!=fid]
    target[3]=[row[0],s.atom(len(remaining))]+remaining
    return s.native_body_bytes([target])


def delete_root_child(request,parent,fid,source,metadata,objects,kind):
    text=request['object_xml']
    if not isinstance(text,str) or len(text.encode('utf-8'))>s.MAX_BYTES or '<!DOCTYPE' in text.upper():raise ValueError('Invalid deletion parent XML')
    root=E.fromstring(text);q='{'+c.MD+'}';children=root[0].find(q+'ChildObjects')
    if children is None:raise ValueError('Root child deletion requires complete Configuration.ChildObjects')
    if any(node.tag==q+kind and node.text==s.val(objects[fid][0][9]) for node in children):raise ValueError('Deleted root child remains in XML')
    E.SubElement(children,q+kind).text=s.val(objects[fid][0][9]);restored=E.tostring(root,encoding='unicode')
    docs=[source];common=s.common_properties(docs,parent,request['platform'])
    baseline=s.configuration_baseline_from_snapshot(restored,parent,common,docs,request['platform'],request['context'])
    s.xml_property_patches(baseline,restored,parent,common,docs,request['platform'],allowed=set(),allow_unchanged=True)
    rows=[]
    def walk(node):
        if isinstance(node,list):
            if len(node)>=2 and not isinstance(node[0],list) and s.val(node[0])==ids.class_id(kind):rows.append(node)
            for child in node:walk(child)
    target=copy.deepcopy(source);walk(target)
    expected={oid for oid,cls in c.children(metadata) if cls==ids.class_id(kind)}
    if len(rows)!=1 or s.val(rows[0][1])!=str(len(rows[0])-2) or {s.val(key) for key in rows[0][2:]}!=expected or len(rows[0])-2!=len(expected):raise ValueError('Common form native collection/context mismatch')
    wanted=[s.val(objects[s.val(key)][0][9]) for key in rows[0][2:] if s.val(key)!=fid]
    if [node.text for node in children if node.tag==q+kind and node.text!=s.val(objects[fid][0][9])]!=wanted:raise ValueError('Deletion XML must preserve remaining root child order')
    rows[0][:]=[rows[0][0],s.atom(len(expected)-1)]+[key for key in rows[0][2:] if s.val(key)!=fid]
    return s.native_body_bytes([target])


def main():
    from serializer_cli import run
    run(serialize)


if __name__=='__main__':main()
