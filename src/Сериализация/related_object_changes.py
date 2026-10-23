"""Whole-XML updates of existing recorders in the same creation transaction."""
import copy,json
from pathlib import Path
import native_metadata as s
import metadata_object_xml as flat
import object_xml_profiles as profiles
import packet_builder as packets
import metadata_identifiers as ids


def apply(request,objects,raws,versions,new_id,kind):
    policy=profiles.profiles().get(kind,{}).get('reverse_references');entries=request.get('related_objects',[])
    if not isinstance(entries,list) or len(entries)>256 or (entries and not policy):raise ValueError('Unsupported related object changes')
    if sum(len(json.dumps(entry).encode('utf-8')) for entry in entries)>s.MAX_BYTES:raise ValueError('Oversized related XML changes')
    if policy and not entries:raise ValueError('Creation requires related recorder Document XML')
    changed=[]
    for entry in entries:
        if not isinstance(entry,dict) or set(entry)!={'kind','object_id','object_xml'} or entry['kind']!=policy['kind']:raise ValueError('Invalid related object input')
        oid=entry['object_id']
        if oid==new_id or oid in changed or oid not in raws or s.val(objects[oid][0][2])!=ids.class_id(entry['kind']):raise ValueError('Related object is missing, duplicated or has another class')
        source=s.Parser(raws[oid].decode('utf-8-sig')).documents()[0]
        import metadata_type_references
        actual_oid,name,raw,_=flat.object_xml(entry['object_xml'],request['platform'],entry['kind'],objects,type_references=metadata_type_references.resolve(entry['object_xml'],request))
        target=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        if actual_oid!=oid or name!=s.val(objects[oid][0][9]):raise ValueError('Related object identity mismatch')
        layout=json.loads(Path(__file__).with_name(entry['kind'].lower()+'_layout_851.json').read_text(encoding='utf-8'))
        profile=layout['reference_lists'][policy['property']];path=profile['path'];old=source;new=target
        for slot in path:old=old[slot];new=new[slot]
        def references(row):
            result=[]
            if s.val(row[0])!='0' or s.val(row[1])!=str(len(row)-2):raise ValueError('Unsupported recorder reference list')
            for item in row[2:]:
                value=item
                for slot in profile['id_path']:value=value[slot]
                key=s.val(value);expected=s.Parser(profile['item_template']).documents()[0];target=expected
                for slot in profile['id_path'][:-1]:target=target[slot]
                target[profile['id_path'][-1]]=s.atom(key)
                if s.render(item)!=s.render(expected):raise ValueError('Unsupported recorder reference entry')
                result.append(key)
            if len(set(result))!=len(result):raise ValueError('Duplicate recorder reference')
            return result
        old_ids,new_ids=references(old),references(new)
        if new_id not in new_ids or set(new_ids)!=set(old_ids)|{new_id}:raise ValueError('Recorder XML must add only the new register and preserve existing records')
        baseline=copy.deepcopy(target);parent=baseline;original=source
        for slot in path[:-1]:parent=parent[slot];original=original[slot]
        parent[path[-1]]=copy.deepcopy(original[path[-1]])
        common=layout.get('common_path',[1,layout.get('common_slot',9)]+([] if layout.get('common_direct') else [1]))
        parent=baseline;original=source
        for slot in common[:-1]:parent=parent[slot];original=original[slot]
        parent[common[-1]]=copy.deepcopy(original[common[-1]])
        if s.render(baseline)!=s.render(source):raise ValueError('Recorder XML or source is outside the verified whole-object profile')
        m=objects[oid][0];relations=s.metadata_relations(m[14]);relations[new_id]=0
        m[14]=[s.atom(len(relations))]+[s.atom(key) for key in relations]+[s.atom(value) for value in relations.values()]
        raws[oid]=raw;versions[oid]=packets.content_version(raw);changed.append(oid)
    return changed
