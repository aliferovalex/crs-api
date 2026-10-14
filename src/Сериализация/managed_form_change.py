"""Replace the current managed interface using the shared whole-file converter."""
import base64,re,uuid
import metadata_serializer as s
import serialization_context as contexts
import metadata_identifiers as ids
import external_data
import managed_form_xml as form_xml
from packet_builder import pack_external_change
import platform_profiles as platforms
import managed_form_profiles as profiles


def serialize(request):
    if not platforms.legacy(request['platform']):raise ValueError('Managed form changes require legacy profile')
    oid=str(uuid.UUID(request['object_id']));attribute=request.get('attribute_name')
    if 'module_text' in request and not isinstance(request['module_text'],str):raise ValueError('Invalid form module text')
    module_only='form_xml' not in request and not attribute and 'module_text' in request
    if 'form_xml' not in request and not module_only and (not isinstance(attribute,str) or not re.fullmatch(r'[^\W\d]\w{0,79}',attribute,re.UNICODE)):raise ValueError('Invalid attribute name')
    storage=contexts.decode(request['storage'],'Oversized form input')
    frame=contexts.read(request,oid,'Oversized form input','Form snapshot/context mismatch');saved,docs,data=frame.saved,frame.docs,frame.data;m=frame.metadata
    kind=ids.class_labels().get(s.val(m[2]))
    kinds={('CommonForm' if owner=='CommonForm' else owner+'Form'):owner for owner in profiles.KINDS}
    if kind not in kinds or s.val(m[4])!=s.ZERO or any(s.render(m[i])!='{0}' for i in (12,13)):raise ValueError('Unsupported form metadata')
    owner_kind=kinds[kind]
    parent_id=s.val(m[3]);name=oid+'.0';refs=m[11]
    if s.metadata_relations(m[14])!={parent_id:1} or s.metadata_relations(saved[0][14])!={parent_id:1} or len(refs)!=3 or s.val(refs[1])!=name:raise ValueError('Unsupported form source stream or relations')
    original=contexts.original_version(request['original_version'],m,'Source version mismatch')
    current=external_data.extract(storage,oid);parent=external_data.extract(storage,parent_id)
    if (current['class_id']!=s.val(m[2]) or current['parent_id']!=parent_id or current['version_number']!=int(s.val(m[5]))
            or current['original']!=original[:32] or current['local']!=uuid.UUID(s.val(m[8])).bytes_le.hex()
            or parent['class_id']!=ids.class_id('Configuration' if owner_kind=='CommonForm' else owner_kind) or len(current['externals'])!=1):raise ValueError('Version storage/snapshot mismatch')
    stream=current['externals'][0]
    if stream['name']!=name or stream['version']!=uuid.UUID(s.val(refs[2])).bytes_le.hex()+'00000000':raise ValueError('External source version mismatch')
    owner=s.Parser(s.inflate(base64.b64decode(parent['data'],validate=True)).decode('utf-8-sig')).documents()[0]
    attributes=owner[6] if not module_only and kind=='CatalogForm' else None
    if attributes is not None and (s.val(attributes[0])!=ids.group_id('CatalogAttributes') or int(s.val(attributes[1]))!=len(attributes)-2):raise ValueError('Unsupported Catalog attributes')
    raw=s.inflate(base64.b64decode(stream['data'],validate=True))
    if 'form_xml' in request:
        import metadata_references
        paths=form_xml.object_paths(owner,owner_kind)
        paths.references=metadata_references.resolve(request['form_xml'],request,storage)
        form=form_xml.interface(raw)
        if kind!='CommonForm' and s.val(form[3][2][5][1][1])!=s.val(owner[1][1]):raise ValueError('Form main Object type mismatch')
        external=form_xml.convert(raw,request['form_xml'],request.get('module_text'),
            paths,profiles.owner_name(owner,owner_kind),owner_kind,parent['parent_id'] if owner_kind=='Report' else None)
    elif not module_only:
        if kind!='CatalogForm':raise ValueError('Compatibility attribute insertion requires a CatalogForm')
        matches=[v for v in attributes[2:] if s.val(v[0][1][1][1][2])==attribute]
        if len(matches)!=1:raise ValueError('Attribute not found or ambiguous')
        pattern=matches[0][0][1][1][2]
        if len(pattern)!=2 or s.val(pattern[0])!='Pattern' or s.val(pattern[1][0])!='S':raise ValueError('Only string attributes are supported')
        form=form_xml.interface(raw)
        if s.val(form[3][1])!='1' or s.val(form[3][2][3])!='Object' or s.val(form[3][2][5][1][1])!=s.val(owner[1][1]):raise ValueError('Form main Object type mismatch')
        external=form_xml.append_attribute(raw,attribute,form_xml.catalog_paths(owner),s.val(owner[1][9][1][2]))
    else:
        external=form_xml.convert(raw,module_text=request['module_text'])
    body=s.inflate(data)
    definition=s.Parser(body.decode('utf-8-sig')).documents()[0]
    common=profiles.common(definition,owner_kind)
    if s.val(common[1][2])!=oid or s.val(common[2])!=s.val(m[9]):raise ValueError('Form body/description mismatch')
    if 'definition_xml' in request:
        import form_definition_xml
        body=form_definition_xml.convert(body,request['definition_xml'],owner_kind,request['platform']);data=s.compress(body)
    return pack_external_change(docs,saved,data,oid,name,original,body,s.compress(external))


def main():
    from serializer_cli import run
    run(serialize)


if __name__=='__main__':main()
