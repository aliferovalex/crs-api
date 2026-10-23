"""Forward, self and enum-value references use actual final native definitions."""
import base64
import copy
import json
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as E

import test_configuration_templates as source_cases
import test_object_xml_profiles as object_cases
import test_enum_serializer as enum_cases
from test_form_kinds_xml import common_xml
from test_managed_form_creation import store
import configuration_commit as commit
import configuration_batch as batch
import form_attribute_types
import managed_form_xml as forms
import metadata_context
import metadata_identifiers as ids
import metadata_object_xml
import metadata_references
import metadata_targets
import native_metadata as s
import native_references
import schema_content
import xml_namespaces

Q=commit.preparation.Q
CORE='{'+xml_namespaces.CORE+'}'


def interface(names=('FreshCatalog','FreshDocument','FreshEnum'),choices=True):
    witness=json.loads(Path(__file__).with_name('fixtures').joinpath('form_enum_choice_interfaces_851.json').read_text(encoding='utf-8'))['cases'][0]['xml']
    root=E.fromstring(common_xml(()));attributes=root.find(forms.Q+'Attributes');items=root.find(forms.Q+'ChildItems')
    for index,(kind,name) in enumerate(zip(('CatalogRef','DocumentRef','EnumRef'),names),1):
        attr=E.SubElement(attributes,forms.Q+'Attribute',name='Value'+str(index),id=str(index));typ=E.SubElement(attr,forms.Q+'Type');E.SubElement(typ,CORE+'Type').text='cfg:'+kind+'.'+name
        field=E.SubElement(items,forms.Q+('RadioButtonField' if choices and index==3 else 'InputField'),name='Field'+str(index),id=str(100+index));E.SubElement(field,forms.Q+'DataPath').text='Value'+str(index)
        if choices and index==3:
            choice=copy.deepcopy(E.fromstring(witness).find('.//'+forms.Q+'ChoiceList'))
            for number,item in enumerate(choice):
                wrapper=item.find('{'+xml_namespaces.READABLE+'}Value');wrapper.set('{http://www.w3.org/2001/XMLSchema-instance}type','lf:FormChoiceListDesTimeValue')
                wrapper.find(forms.Q+'Value').text='Enum.'+name+'.EnumValue.'+('First' if number==0 else 'Second')
            field.append(choice)
    return xml_namespaces.render(root,witness.replace('<Form ','<Form xmlns:lf="'+forms.NS+'" ',1))


class FinalNativeReferenceTests(unittest.TestCase):
    def case(self):
        helper=source_cases.ConfigurationTemplateTests();r,source,objects,paths,target=helper.fixture(common=True);self.addCleanup(helper.doCleanups)
        root_path=target/'Configuration.xml';root=E.parse(root_path);children=root.getroot()[0].find(Q+'ChildObjects')
        schema=json.loads(Path(__file__).with_name('fixtures').joinpath('template_packets_851.json').read_text(encoding='utf-8'))['reference_request']['template_xml']
        owner_ids={};form_ids=[];schema_ids={}
        for number,(kind,name) in enumerate(zip(('Catalog','Document','Enum'),('FreshCatalog','FreshDocument','FreshEnum')),1):
            oid=str(uuid.UUID(int=0xeeeeeeee000040008000000000000000+number));owner_ids[kind]=oid
            top=E.fromstring(enum_cases.xml() if kind=='Enum' else object_cases.xml(kind));top[0].set('uuid',oid);top[0].find(Q+'Properties/'+Q+'Name').text=name
            fid=str(uuid.UUID(int=0xeeeeeeee000040008000000000000010+number));form_ids.append(fid)
            E.SubElement(top[0].find(Q+'ChildObjects'),Q+'Form').text='References'
            path=target/commit.export.folder(kind)/(name+'.xml');path.parent.mkdir(exist_ok=True);path.write_bytes(E.tostring(top,encoding='utf-8'))
            E.SubElement(children,Q+kind).text=name
            self.form_files(path.with_suffix('')/'Forms/References.xml',fid,'Form',interface())
            tid=str(uuid.UUID(int=0xeeeeeeee000040008000000000000020+number));schema_ids[kind]=tid
            definition=E.fromstring(json.loads(Path(__file__).with_name('fixtures').joinpath('common_template_packets_851.json').read_text(encoding='utf-8'))['create']['definition_xml'])
            definition[0].set('uuid',tid);definition[0].find(Q+'Properties/'+Q+'Name').text='Schema'+kind
            file=target/'CommonTemplates'/('Schema'+kind+'.xml');file.parent.mkdir(exist_ok=True);file.write_bytes(E.tostring(definition,encoding='utf-8'))
            E.SubElement(children,Q+'CommonTemplate').text='Schema'+kind
            ext=file.with_suffix('')/'Ext';ext.mkdir(parents=True);(ext/'Template.xml').write_text(schema.replace('CatalogRef.CRSAPI_FullCatalog',kind+'Ref.'+name),encoding='utf-8')
        fid=str(uuid.UUID(int=0xeeeeeeee000040008000000000000030));form_ids.append(fid)
        self.form_files(target/'CommonForms/References.xml',fid,'CommonForm',interface());E.SubElement(children,Q+'CommonForm').text='References'
        root.write(root_path,encoding='utf-8')
        for oid,docs in objects.items():
            if oid not in r['snapshots']:
                r['snapshots'][oid]=store(docs,b'unchanged opaque source body');r['originals'][oid]=uuid.UUID(s.val(docs[0][7])).bytes_le.hex()+'00000000'
        plan,_=commit.prepare(r);r.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
        return r,objects,owner_ids,form_ids,schema_ids

    def form_files(self,path,fid,kind,xml):
        top=E.Element(Q+'MetaDataObject',version='2.21');node=E.SubElement(top,Q+kind,uuid=fid);E.SubElement(E.SubElement(node,Q+'Properties'),Q+'Name').text=path.stem
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(E.tostring(top,encoding='utf-8'));ext=path.with_suffix('')/'Ext';ext.mkdir(parents=True);(ext/'Form.xml').write_text(xml,encoding='utf-8')

    def test_new_types_and_values_match_created_bodies_in_owned_and_common_forms_and_schemas(self):
        r,objects,owners,form_ids,schemas=self.case();before_context=r['context'];before_snapshots=set(r['snapshots'])
        with patch.object(commit.packets,'assemble',wraps=commit.packets.assemble) as assemble,patch.object(metadata_object_xml,'create',wraps=metadata_object_xml.create) as create:
            result=commit.serialize(r);self.assertEqual(assemble.call_count,1);self.assertEqual(create.call_count,3)
        self.assertEqual(r['context'],before_context);self.assertEqual(set(r['snapshots']),before_snapshots)
        self.assertTrue(set(owners.values()).isdisjoint(objects));self.assertTrue(set(owners.values()).isdisjoint(r['snapshots']))
        _,records=batch.read_packet(result['data']);by_id={record.object_id:record for record in records};types={}
        for kind,oid in owners.items():
            body=s.Parser(s.inflate(by_id[oid].body).decode('utf-8-sig')).documents()[0]
            identity=metadata_targets.Target(oid,ids.class_id(kind),'',s.ZERO,'Fresh'+kind)
            types[kind]=form_attribute_types.generated_identity(body,identity,kind)
        for fid in form_ids:
            native=forms.interface(s.inflate(by_id[fid].externals[0][1]));attrs={s.val(attr[3]):attr for attr in native[3][2:2+int(s.val(native[3][1]))]}
            for index,kind in enumerate(owners,1):self.assertEqual(s.render(attrs['Value'+str(index)][5]),'{"Pattern",{"#",'+types[kind]+'}}')
            text=s.render(native);self.assertIn(enum_cases.V1,text);self.assertIn(enum_cases.V2,text)
        for kind,tid in schemas.items():
            raw=b''.join(schema_content.unpack(s.inflate(by_id[tid].externals[0][1])))
            self.assertIn(types[kind].encode(),raw);self.assertNotIn(owners[kind].encode(),raw)

    def test_final_identity_selection_rejects_removed_and_not_yet_compiled_targets(self):
        r,objects,owners,_,_=self.case();targets=metadata_targets.Index([row for row in metadata_targets.index(objects).targets if row.class_id!=ids.class_id('Catalog')])
        reader=native_references.Catalog(r,targets);old=next(s.val(d[0][9]) for d in objects.values() if s.val(d[0][2])==ids.class_id('Catalog'))
        with self.assertRaisesRegex(ValueError,'missing from current context or final configuration'):
            metadata_references.resolve(interface((old,),False),dict(r,_native_references=reader))
        target=metadata_targets.Target(owners['Catalog'],ids.class_id('Catalog'),'',s.ZERO,'FreshCatalog')
        reader=native_references.Catalog(r,metadata_targets.Index([target]))
        with self.assertRaisesRegex(ValueError,'not compiled'):metadata_references.resolve(interface(('FreshCatalog',),False),dict(r,_native_references=reader))

    def test_updated_enum_values_use_compiled_feature_map(self):
        import test_metadata_references as source
        source.ReferenceTests.setUpClass();r,_=source.ReferenceTests().fixture()
        reader=native_references.Catalog(r);identity=next(row for row in reader.targets.targets if row.class_id==ids.class_id('Enum'))
        entry=reader.load(identity);body=s.Parser(entry.body.decode('utf-8-sig')).documents()[0]
        value=copy.deepcopy(body[6][2]);vid='dddddddd-dddd-4ddd-8ddd-dddddddddddd'
        value[0][1][1][2]=s.atom(vid);value[0][1][2]=s.atom('Added',True);body[6].append(value);body[6][1]=s.atom(len(body[6])-2)
        reader.register(identity.object_id,s.native_body_bytes([body]),entry.features|{vid})
        ref='Enum.'+identity.name+'.EnumValue.Added'
        xml='<Form xmlns:xr="'+xml_namespaces.READABLE+'" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><Value xsi:type="xr:DesignTimeRef">'+ref+'</Value></Form>'
        with self.assertRaisesRegex(ValueError,'value is missing'):metadata_references.resolve(xml,r)
        resolved=metadata_references.resolve(xml,dict(r,_native_references=reader));self.assertEqual(resolved[ref][1],vid)

    def test_prepared_creation_cannot_be_reused_for_different_xml(self):
        import test_owned_template_creation as source
        r=source.request();objects=metadata_context.context_objects(r['context'])
        forms={entry['name']:E.fromstring(entry['definition_xml'])[0].get('uuid') for entry in r['forms']}
        templates={entry['name']:E.fromstring(entry['definition_xml'])[0].get('uuid') for entry in r['templates']}
        prepared=metadata_object_xml.prepare_creation(r['object_xml'],r['platform'],'Catalog',forms,objects,r['object_id'],None,templates)
        root=E.fromstring(r['object_xml']);root[0].find(Q+'Properties/'+Q+'Comment').text='Changed comment'
        r['object_xml']=xml_namespaces.render(root,r['object_xml'])
        import object_creation_serializer
        with self.assertRaisesRegex(ValueError,'Prepared creation definition differs'):
            object_creation_serializer.serialize(r,definition=prepared)

    def test_single_owner_entry_resolves_its_own_new_form_and_schema_types(self):
        import test_owned_template_creation as source
        import object_creation_serializer
        r=source.request();name=E.fromstring(r['object_xml'])[0].findtext(Q+'Properties/'+Q+'Name')
        for entry in r['forms']:entry['form_xml']=interface((name,),False)
        schema=json.loads(Path(__file__).with_name('fixtures').joinpath('template_packets_851.json').read_text(encoding='utf-8'))['reference_request']['template_xml']
        r['templates'][2]['template_xml']=schema.replace('CatalogRef.CRSAPI_FullCatalog','CatalogRef.'+name)
        result=object_creation_serializer.serialize(r);_,records=batch.read_packet(result['data']);by_id={row.object_id:row for row in records}
        body=s.Parser(s.inflate(by_id[result['object_id']].body).decode('utf-8-sig')).documents()[0]
        identity=metadata_targets.Target(result['object_id'],ids.class_id('Catalog'),'',s.ZERO,name)
        typ=form_attribute_types.generated_identity(body,identity,'Catalog')
        for entry in r['forms']:
            fid=E.fromstring(entry['definition_xml'])[0].get('uuid');native=forms.interface(s.inflate(by_id[fid].externals[0][1]))
            self.assertEqual(s.render(native[3][2][5]),'{"Pattern",{"#",'+typ+'}}')
        tid=E.fromstring(r['templates'][2]['definition_xml'])[0].get('uuid')
        self.assertIn(typ.encode(),b''.join(schema_content.unpack(s.inflate(by_id[tid].externals[0][1]))))


if __name__=='__main__':unittest.main()
