"""Build a factual XML child map and annotate current native profile coverage.

The XSD input stays external to the package. No network or platform is required.
"""
import argparse,ast,hashlib,json,sys
from pathlib import Path
from xml.etree import ElementTree as E

X='{http://www.w3.org/2001/XMLSchema}'
MD='http://v8.1c.ru/8.3/MDClasses'
ALIASES={'ChartOfCharacteristicTypes':'ChartOfCharacteristicType','DocumentNumerator':'DocumentNumerators','Sequence':'Sequences'}


def schema_classes(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('Schema entities are unsupported')
    root=E.fromstring(raw)
    if root.tag!=X+'schema' or root.get('targetNamespace')!=MD:raise ValueError('Expected MDClasses XSD')
    types={node.get('name'):node for node in root.findall(X+'complexType')}
    def elements(name):
        if name not in types:raise ValueError('Missing local schema type: '+str(name))
        return list(types[name].iter(X+'element'))
    exported={node.get('name') for node in elements('MetaDataObject')}
    result={}
    for name,node in types.items():
        fields=list(node.iter(X+'element'));props=next((e for e in fields if e.get('name')=='Properties'),None)
        if props is None:continue
        child=next((e for e in fields if e.get('name')=='ChildObjects'),None)
        collections=[]
        if child is not None:
            for item in elements(child.get('type').split(':')[-1]):
                tag=item.get('name');typ=item.get('type')
                if not tag or not typ:raise ValueError('Unsupported child declaration')
                collections.append(dict(xml_name=tag,xml_type=typ,storage='stored_name' if typ=='xs:string' else 'inline_xml',
                                        item_type=tag if typ=='xs:string' else typ.split(':')[-1],min_occurs=item.get('minOccurs','1'),max_occurs=item.get('maxOccurs','1')))
        result[name]=dict(xml_name=name,exported=name in exported,collections=collections,
                          properties=[p.get('name') for p in elements(props.get('type').split(':')[-1])])
    for owner in result.values():
        for collection in owner['collections']:
            if collection['item_type'] not in result:raise ValueError('Unmapped schema child type: '+collection['item_type'])
    return result


def enrich(classes,source_dir,upstream_types=None):
    dictionary=json.loads((source_dir/'metadata_class_names.json').read_text(encoding='utf-8-sig'))
    names=dictionary['names']
    known={label:identifier for identifier,label in names.items()}
    upstream={}
    if upstream_types:
        tree=ast.parse(Path(upstream_types).read_text(encoding='utf-8-sig'))
        for node in tree.body:
            if isinstance(node,ast.ClassDef) and node.name=='MetaDataTypes':
                for field in node.body:
                    if isinstance(field,ast.Assign) and isinstance(field.value,ast.Constant) and isinstance(field.value.value,str):
                        upstream[field.targets[0].id]=field.value.value
    registry=json.loads((source_dir/'object_xml_profiles.json').read_text(encoding='utf-8-sig'))
    editor_profiles=json.loads((source_dir/'collection_editor_profiles_851.json').read_text(encoding='utf-8-sig'))
    form_owners=json.loads((source_dir/'managed_form_owner_profiles_851.json').read_text(encoding='utf-8-sig'))
    opaque_owners=json.loads((source_dir/'opaque_owner_profiles_851.json').read_text(encoding='utf-8-sig'))
    sys.path.insert(0,str(source_dir))
    import native_metadata as native_text
    layouts={}
    for path in source_dir.glob('*_layout_851.json'):
        layouts[path.stem.removesuffix('_layout_851')]=json.loads(path.read_text(encoding='utf-8-sig'))
    for xml_name,record in classes.items():
        kind=ALIASES.get(xml_name,xml_name);record['runtime_name']=kind
        record['class_id']=known.get(kind);record['modules']=registry.get(kind,{}).get('modules',{})
        layout=layouts.get(kind.lower(),{})
        if kind=='Configuration':record['native_identity_path']=[1,0]
        elif layout:
            common=layout.get('common_path',[1,layout.get('common_slot',9)]+([] if layout.get('common_direct') else [1]))
            record['native_identity_path']=common+[1,2]
        else:record['native_identity_path']=None
        if kind in form_owners:record['native_identity_path']=form_owners[kind]['owner_identity_path']
        record['automatic_deletion_supported']=kind in ('Configuration','Catalog') or (kind in registry and bool(layout.get('child_collections') or editor_profiles.get(kind)))
        if kind in form_owners:record['automatic_deletion_supported']=True
        if kind in opaque_owners:
            record['native_identity_path']=opaque_owners[kind]['owner_identity_path']
            record['automatic_deletion_supported']=True
        record['content_files']={}
        for name,rule in registry.get(kind,{}).get('files',{}).items():
            record['content_files']['Ext/'+rule['file']]={'serializer':'object_file_content','status':'partial' if rule.get('partial') else 'supported','native_suffix':rule['suffix']}
        if xml_name in ('Form','CommonForm'):
            record['content_files']={'Ext/Form.xml':{'serializer':'managed_form_xml','status':'partial'},'Ext/Form/Module.bsl':{'serializer':'managed_form_xml','status':'supported'}}
        elif xml_name in ('Template','CommonTemplate'):
            record['content_files']={file:{'serializer':'template_content','status':'supported_for_selected_template_types'} for file in ('Ext/Template.xml','Ext/Template.bin','Ext/Template.txt')}
        if kind=='CommonModule':record['modules']={'Module':'.0'}
        for collection in record['collections']:
            tag=collection['xml_name'];storage=collection['storage']
            native=dict(status='unmapped',path=None,collection_id=None,serializer=None)
            child_kind=(kind+'Form') if tag=='Form' else ALIASES.get(tag,tag)
            if kind=='ExternalDataSource' and tag in ('Table','Cube'):child_kind=tag
            collection['runtime_item_kind']=child_kind if storage=='stored_name' else kind+tag
            collection['item_class_id']=known.get(child_kind)
            if collection['item_class_id'] is None and storage=='stored_name' and child_kind in upstream:
                collection['item_class_id']=upstream[child_kind];collection['class_id_evidence']='v8unpack_enum'
            elif collection['item_class_id']:collection['class_id_evidence']='project_dictionary'
            if kind=='Configuration':
                native.update(status='snapshot_collection',collection_id=collection['item_class_id'],serializer='automatic_deletion.owner_content',lookup='class UUID collection in current snapshot')
                if not collection['item_class_id']:native['status']='unmapped'
            for category,handler in (('child_collections','child_object_xml'),('inline_collections','inline_object_xml'),('tabular_collections','tabular_section_xml'),('command_collections','inline_metadata_xml'),('structured_collections','inline_metadata_xml')):
                profile=layout.get(category,{}).get(tag)
                if profile:
                    native.update(status='verified_profile',path=[profile['slot']],collection_id=profile.get('collection_id') or profile.get('class_id') or known.get(profile.get('kind')),serializer=handler)
            if kind=='Enum' and tag=='EnumValue':native.update(status='verified_profile',path=[layout['values_slot']],serializer='inline_object_xml')
            editor_profile=editor_profiles.get(kind,{}).get(tag)
            if editor_profile:
                if collection['item_class_id']!=editor_profile['class_id']:raise ValueError('Editor and schema collection UUIDs differ')
                native.update(status='snapshot_collection',path=None,collection_id=editor_profile['class_id'],serializer='native_collection_editor',lookup=editor_profile['lookup'],evidence=editor_profile['evidence'])
            if native['status']=='verified_profile' and native['collection_id'] is None and native['path'] is not None:
                body=native_text.Parser(layout['template']).documents()[0]
                for slot in native['path']:body=body[slot]
                identifier=native_text.val(body[0])
                import uuid
                try:native['collection_id']=str(uuid.UUID(identifier))
                except ValueError:pass
            if kind in form_owners and (tag in ('Form','Template') or kind=='Cube' and tag=='DimensionTable') and collection['item_class_id'] and native['status']!='verified_profile':
                native.update(status='snapshot_collection',path=None,collection_id=collection['item_class_id'],serializer='native_collection_editor',lookup='snapshot_class_collection',evidence=form_owners[kind]['source'])
            if native['status']=='unmapped' and collection['item_class_id'] and layout.get('template'):
                candidates=[]
                def locate(node,path=()):
                    if not isinstance(node,list):return
                    if len(node)>=2 and not isinstance(node[0],list) and native_text.val(node[0])==collection['item_class_id']:
                        candidates.append(list(path))
                    for index,item in enumerate(node):locate(item,path+(index,))
                locate(native_text.Parser(layout['template']).documents()[0])
                if len(candidates)==1:
                    native['candidate_path']=candidates[0]
                    native['candidate_evidence']=kind.lower()+'_layout_851.json template; write handler not implemented'
            native['format']=('class_uuid,count,object_uuids' if storage=='stored_name' else 'collection_uuid,count,inline_entries') if native['status']!='unmapped' else 'unknown'
            collection['native']=native
            explicit=opaque_owners.get(kind,{}).get('collections',{}).get(tag)
            if explicit:
                if explicit['kind']!=collection['runtime_item_kind'] or not collection['item_class_id']:raise ValueError('Opaque owner collection class differs from schema')
                native.update(status='verified_profile',path=explicit['path'],collection_id=collection['item_class_id'],serializer='native_collection_editor',format='class_uuid,count,object_uuids',evidence=opaque_owners[kind]['source'])
    # TabularSection has an owner-specific native layout, not one global UUID.
    for owner in registry:
        profile=layouts.get(owner.lower()+'_tabular')
        if profile and 'TabularSection' in classes:
            collection=classes['TabularSection']['collections'][0]
            collection.setdefault('owner_native_profiles',{})[owner]=dict(status='verified_profile',collection_id=profile['attribute_collection_id'],serializer='tabular_section_xml')
    def nested(rule):
        for tag,child in rule.get('children',{}).items():
            row=next(c for c in classes[rule['xml_name']]['collections'] if c['xml_name']==tag)
            row['native'].update(status='verified_profile',path=child['path'],path_scope='inline_object',collection_id=child['collection_id'],serializer='inline_metadata_xml')
            nested(child)
    for kind in registry:
        for rule in layouts.get(kind.lower(),{}).get('structured_collections',{}).values():nested(rule)
    return classes


def main():
    parser=argparse.ArgumentParser();parser.add_argument('schema',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--source-url',required=True);parser.add_argument('--format',default='2.21');parser.add_argument('--upstream-types',type=Path)
    args=parser.parse_args();raw=args.schema.read_bytes();source_dir=next((Path(__file__).resolve().parents[1]/'src').rglob('metadata_class_names.json')).parent
    classes=enrich(schema_classes(raw),source_dir,args.upstream_types)
    data=dict(schema_version=1,xml_format=args.format,source=dict(url=args.source_url,sha256=hashlib.sha256(raw).hexdigest()),native_profile='8.5.1.1529',classes=classes)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Metadata classes:',len(classes),'collections:',sum(len(v['collections']) for v in classes.values()))


if __name__=='__main__':main()
