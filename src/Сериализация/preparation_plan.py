"""Resolve one XML export file into a supported repository preparation operation."""
from pathlib import Path
from xml.etree import ElementTree as E
import metadata_serializer as s
import metadata_identifiers as ids
import constant_serializer as c
import object_xml_profiles as profiles

Q='{'+c.MD+'}'
FORM_KINDS={'CatalogForm','DocumentForm','CommonForm','DataProcessorForm','ReportForm'}
CREATE=set(profiles.creation_types())|FORM_KINDS|{'Template','CommonTemplate'}
CHANGE=set(profiles.profiles())|{'Configuration','Template','CommonTemplate'}|FORM_KINDS


def read(path):
    path=Path(path)
    if not path.is_file() or path.stat().st_size>s.MAX_BYTES:raise ValueError('Missing or oversized export file: '+str(path))
    return path.read_text(encoding='utf-8-sig')


def metadata(text):
    if '<!DOCTYPE' in text.upper():raise ValueError('DOCTYPE is unsupported')
    root=E.fromstring(text)
    if root.tag!=Q+'MetaDataObject' or len(root)!=1:raise ValueError('Expected one metadata object XML, not Ext/Form.xml')
    obj=root[0];kind=obj.tag.removeprefix(Q)
    if obj.tag!=Q+kind or set(obj.attrib)!={'uuid'}:raise ValueError('Invalid metadata XML object')
    oid=c.guid(obj.get('uuid'));props=obj.findall(Q+'Properties')
    if len(props)!=1:raise ValueError('Missing or duplicate Properties')
    names=props[0].findall(Q+'Name')
    if len(names)!=1 or len(names[0]) or not names[0].text:raise ValueError('Missing or duplicate object Name')
    return kind,oid,names[0].text


def plan(request):
    options=request.get('options',{})
    if not isinstance(options,dict) or set(options)-{'operation','object_id','parent_id','before_xml_path','related_xml_paths'}:raise ValueError('Unknown preparation option')
    operation=options.get('operation','Авто')
    if operation not in ('Авто','Создание','Изменение','Удаление'):raise ValueError('Unknown preparation operation')
    path=Path(request['xml_path']).resolve();text=read(path);kind,oid,name=metadata(text)
    objects=c.context_objects(request['context'])
    roots=[key for key,d in objects.items() if s.val(d[0][2])==ids.class_id('Configuration') and s.val(d[0][3])==s.ZERO]
    if len(roots)!=1:raise ValueError('Context must contain exactly one Configuration root')
    root_id=roots[0];module=None;form=None;before=None;forms=[];modules={};inline_modules=[];related=[]
    if operation=='Удаление':
        if kind not in ('Catalog','Document','DataProcessor','Report','Configuration') or not options.get('object_id'):raise ValueError('Deletion requires parent XML and explicit form UUID')
        removed=c.guid(options['object_id'])
        label=ids.class_labels().get(s.val(objects[removed][0][2])) if removed in objects else None
        form_kind='CommonTemplate' if label=='CommonTemplate' and kind=='Configuration' else ('Template' if label=='Template' and kind!='Configuration' else ('CommonForm' if kind=='Configuration' else kind+'Form'))
        if removed not in objects or s.val(objects[removed][0][2])!=ids.class_id(form_kind) or s.val(objects[removed][0][3])!=oid or oid not in objects or s.val(objects[oid][0][2])!=ids.class_id(kind):
            raise ValueError('Deletion form is missing or belongs to another parent')
        if options.get('parent_id') or options.get('before_xml_path') or options.get('related_xml_paths'):raise ValueError('Unexpected deletion options')
        return dict(operation=operation,kind=form_kind,object_id=removed,parent_id=oid,name=name,
                    object_xml=text,form_xml=None,module_text=None,before_xml=None)
    if options.get('object_id'):raise ValueError('Object UUID comes from XML; explicit UUID is only for deletion')
    existing=objects.get(oid)
    parent=root_id
    if kind in ('Template','CommonTemplate'):
        if kind=='CommonTemplate':parent=root_id
        elif existing:parent=s.val(existing[0][3])
        elif options.get('parent_id'):parent=c.guid(options['parent_id'])
        else:
            if path.parent.name!='Templates':raise ValueError('New Template needs standard export path or parent_id')
            _,parent,_=metadata(read(path.parent.parent.with_suffix('.xml')))
        if parent not in objects or ids.class_labels().get(s.val(objects[parent][0][2])) not in ({'Configuration'} if kind=='CommonTemplate' else {'Catalog','Document','DataProcessor','Report'}):
            raise ValueError('Unsupported or missing Template owner')
    elif kind=='Form':
        if existing:
            label=ids.class_labels().get(s.val(existing[0][2]))
            if label not in FORM_KINDS-{'CommonForm'}:raise ValueError('XML Form UUID matches another metadata class')
            kind=label;parent=s.val(existing[0][3])
        elif options.get('parent_id'):
            parent=c.guid(options['parent_id'])
            if parent not in objects:raise ValueError('Form parent is missing')
            label=ids.class_labels().get(s.val(objects[parent][0][2]))
            if label is None or label+'Form' not in FORM_KINDS:raise ValueError('Unsupported form parent')
            kind=label+'Form'
        else:
            owners={'Catalogs':'Catalog','Documents':'Document','DataProcessors':'DataProcessor','Reports':'Report'}
            if path.parent.name!='Forms' or path.parent.parent.parent.name not in owners:raise ValueError('New form needs standard export path or parent_id')
            parent_path=path.parent.parent.with_suffix('.xml')
            pk,parent,_=metadata(read(parent_path))
            expected=owners[path.parent.parent.parent.name]
            if pk!=expected or parent not in objects or s.val(objects[parent][0][2])!=ids.class_id(pk):raise ValueError('Form parent XML does not match repository')
            kind=pk+'Form'
    elif options.get('parent_id'):
        if c.guid(options['parent_id'])!=parent:raise ValueError('Top-level object parent must be the Configuration root')
    if kind not in CREATE|CHANGE:raise ValueError('Unsupported metadata class: '+kind)
    if options.get('parent_id') and c.guid(options['parent_id'])!=parent:raise ValueError('Explicit parent does not match repository or export')
    if existing and s.val(existing[0][2])!=ids.class_id(kind):raise ValueError('XML UUID matches another repository class')
    if existing and s.val(existing[0][3])!=(s.ZERO if kind=='Configuration' else parent):raise ValueError('XML parent does not match repository')
    inferred='Изменение' if existing else 'Создание'
    if operation=='Авто':operation=inferred
    elif operation!=inferred:raise ValueError('Requested operation conflicts with repository object existence')
    if operation=='Создание' and kind not in CREATE or operation=='Изменение' and kind not in CHANGE:raise ValueError('Unsupported operation for '+kind)
    if kind in ('Template','CommonTemplate'):
        import template_serializer
        template_serializer.definition(text,request.get('platform','8.5.1.1529'))
        import template_content
        return dict(operation=operation,kind=kind,object_id=oid,parent_id=parent,name=name,object_xml=text,
                    **template_content.companion(path,text),form_xml=None,module_text=None,before_xml=None)
    reverse=profiles.profiles().get(kind,{}).get('reverse_references')
    paths=options.get('related_xml_paths',[])
    if not isinstance(paths,list) or len(paths)>256:raise ValueError('Related XML paths must be a bounded array')
    if paths and (operation!='Создание' or not reverse):raise ValueError('Related XML changes are unsupported for this operation')
    if reverse and operation=='Создание' and not paths:raise ValueError('Creation requires related recorder Document XML')
    seen=set()
    for related_path in paths:
        value=read(related_path);rk,roid,rname=metadata(value)
        if rk!=reverse['kind'] or roid in seen or roid not in objects or s.val(objects[roid][0][2])!=ids.class_id(rk) or s.val(objects[roid][0][9])!=rname:raise ValueError('Related XML identity does not match repository')
        directory=Path(related_path).with_suffix('')/'Ext'
        if directory.exists() and any(directory.iterdir()):raise ValueError('Related module or companion changes are unsupported')
        seen.add(roid);related.append(dict(kind=rk,object_id=roid,object_xml=value))
    if kind=='CommonModule':module=read(path.with_suffix('')/'Ext'/'Module.bsl')
    for filename,suffix in profiles.module_files(kind).items():
        module_path=path.with_suffix('')/'Ext'/(filename+'.bsl')
        if module_path.exists():modules[filename]=read(module_path)
    if kind=='Document':
        children=E.fromstring(text)[0].find(Q+'ChildObjects')
        for command in ([] if children is None else children):
            if command.tag!=Q+'Command':continue
            cid=c.guid(command.get('uuid'));node=command.find(Q+'Properties/'+Q+'Name');cname=node.text if node is not None else ''
            if not cname or Path(cname).name!=cname or '/' in cname or '\\' in cname or cname in ('.','..'):raise ValueError('Invalid command module path')
            module_path=path.with_suffix('')/'Commands'/cname/'Ext'/'CommandModule.bsl'
            if module_path.exists():inline_modules.append(dict(object_id=cid,source_text=read(module_path)))
    if kind in profiles.profiles():
        ext=path.with_suffix('')/'Ext'
        if ext.exists():
            allowed={n+'.bsl' for n in profiles.module_files(kind)}|({'Module.bsl'} if kind=='CommonModule' else set())
            if any(p.name not in allowed for p in ext.iterdir()):raise ValueError('Unsupported companion export files for '+kind)
    if kind=='Catalog' and operation=='Создание':
        children=E.fromstring(text)[0].find(Q+'ChildObjects');names=[];seen=set(objects)|{oid}
        for node in ([] if children is None else children):
            if node.tag!=Q+'Form':continue
            fname=node.text or ''
            if node.attrib or len(node) or not fname or fname in names or Path(fname).name!=fname or fname in ('.','..') or '/' in fname or '\\' in fname:raise ValueError('Invalid or duplicate Catalog Form reference')
            definition=read(path.with_suffix('')/'Forms'/(fname+'.xml'));fk,fid,actual_name=metadata(definition)
            if fk!='Form' or actual_name!=fname or fid in seen:raise ValueError('Catalog form definition name, UUID or class mismatch')
            seen.add(fid);names.append(fname)
            directory=path.with_suffix('')/'Forms'/fname/'Ext';module_path=directory/'Form'/'Module.bsl'
            forms.append(dict(name=fname,definition_xml=definition,form_xml=read(directory/'Form.xml'),module_text=read(module_path) if module_path.exists() else None))
    if kind in FORM_KINDS:
        form=read(path.with_suffix('')/'Ext'/'Form.xml')
        module_path=path.with_suffix('')/'Ext'/'Form'/'Module.bsl'
        if module_path.exists():module=read(module_path)
    if options.get('before_xml_path'):
        if kind!='Configuration' or operation!='Изменение':raise ValueError('Baseline XML is only supported for Configuration')
        before=read(options['before_xml_path'])
    return dict(operation=operation,kind=kind,object_id=oid,parent_id=parent,name=name,
                object_xml=text,form_xml=form,module_text=module,before_xml=before,forms=forms,modules=modules,inline_modules=inline_modules,related_objects=related)


def main():
    from serializer_cli import run
    run(plan)


if __name__=='__main__':main()
