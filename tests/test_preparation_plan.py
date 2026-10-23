"""Dispatch is based on XML identity plus the current repository context."""
import base64,copy,sys,tempfile,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import preparation_plan as p
import metadata_context
import native_metadata as s
import test_configuration_serializer as root

CID='33333333-3333-4333-8333-333333333333';FID='44444444-4444-4444-8444-444444444444'


class PreparationPlanTests(unittest.TestCase):
    def test_report_and_processor_form_creation_and_change_from_standard_export(self):
        for kind,folder in [('DataProcessor','DataProcessors'),('Report','Reports')]:
            with self.subTest(kind=kind):
                self.objects={root.ID:self.objects[root.ID]}
                self.add(CID,kind,root.ID,'Owner')
                self.xml(Path(folder)/'Owner.xml',kind,CID,'Owner')
                path=self.xml(Path(folder)/'Owner/Forms/Managed.xml','Form',FID,'Managed')
                ext=path.with_suffix('')/'Ext';ext.mkdir(parents=True,exist_ok=True)
                (ext/'Form.xml').write_text('<Form/>',encoding='utf-8')
                result=self.plan(path)
                self.assertEqual((result['kind'],result['operation'],result['parent_id']),(kind+'Form','Создание',CID))
                self.add(FID,kind+'Form',CID,'Managed')
                result=self.plan(path)
                self.assertEqual((result['kind'],result['operation'],result['parent_id']),(kind+'Form','Изменение',CID))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.dir=Path(self.temp.name)
        r,_=root.property_fixture('8.5.1.1529');self.objects={root.ID:metadata_context.context_metadata(base64.b64decode(r['context']),root.ID)}

    def add(self,oid,kind,parent,name='Item'):
        docs=copy.deepcopy(self.objects[root.ID]);m=docs[0]
        m[1],m[2],m[3],m[9]=s.atom(oid),s.atom(p.ids.class_id(kind)),s.atom(parent),s.atom(name,True)
        m[12],m[13],m[14]=[s.atom(0)],[s.atom(0)],[s.atom(0)]
        self.objects[oid]=docs

    def xml(self,path,kind,oid,name='Item'):
        top=E.Element(p.Q+'MetaDataObject',version='2.21');obj=E.SubElement(top,p.Q+kind,uuid=oid)
        E.SubElement(E.SubElement(obj,p.Q+'Properties'),p.Q+'Name').text=name
        path=self.dir/path;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(E.tostring(top,encoding='unicode'),encoding='utf-8')
        return path

    def plan(self,path,**options):
        for oid,docs in self.objects.items():
            rows={}
            for child,child_docs in self.objects.items():
                if s.val(child_docs[0][3])==oid:rows.setdefault(s.val(child_docs[0][2]),[]).append(child)
            docs[0][12]=[s.atom(len(rows))]+[[s.atom(cls),s.atom(len(children))]+[s.atom(child) for child in children] for cls,children in rows.items()]
        context=s.storage([s.text_bytes(d) for d in self.objects.values()],s.text_bytes([[s.atom(0)]]))
        return p.plan(dict(xml_path=str(path),context=base64.b64encode(context).decode(),options=options))

    def test_create_and_modify_and_explicit_conflicts(self):
        path=self.xml(Path('Catalogs/Item.xml'),'Catalog',CID)
        self.assertEqual(self.plan(path)['operation'],'Создание')
        with self.assertRaisesRegex(ValueError,'conflicts'):self.plan(path,operation='Изменение')
        self.add(CID,'Catalog',root.ID)
        self.assertEqual(self.plan(path)['operation'],'Изменение')
        with self.assertRaisesRegex(ValueError,'conflicts'):self.plan(path,operation='Создание')

    def test_form_parent_and_companion_files(self):
        self.add(CID,'Catalog',root.ID);self.xml(Path('Catalogs/Item.xml'),'Catalog',CID)
        path=self.xml(Path('Catalogs/Item/Forms/NewForm.xml'),'Form',FID,'NewForm')
        ext=path.with_suffix('')/'Ext';ext.mkdir(parents=True);(ext/'Form.xml').write_text('<Form/>',encoding='utf-8')
        (ext/'Form').mkdir();(ext/'Form/Module.bsl').write_text('',encoding='utf-8')
        plan=self.plan(path);self.assertEqual(plan['kind'],'CatalogForm');self.assertEqual(plan['parent_id'],CID)
        self.assertEqual(plan['form_xml'],'<Form/>');self.assertEqual(plan['module_text'],'')
        self.add(FID,'CatalogForm',CID,'NewForm');self.assertEqual(self.plan(path)['operation'],'Изменение')
        with self.assertRaisesRegex(ValueError,'Explicit parent'):self.plan(path,parent_id=root.ID)
        (ext/'Form/Module.bsl').unlink();self.assertIsNone(self.plan(path)['module_text'])
        (ext/'Form.xml').unlink()
        with self.assertRaisesRegex(ValueError,'Missing'):self.plan(path)

    def test_module_source_required(self):
        path=self.xml(Path('CommonModules/Item.xml'),'CommonModule',CID)
        with self.assertRaisesRegex(ValueError,'Missing'):self.plan(path)
        ext=path.with_suffix('')/'Ext';ext.mkdir(parents=True);(ext/'Module.bsl').write_text('Function F() EndFunction',encoding='utf-8')
        self.assertEqual(self.plan(path)['module_text'],'Function F() EndFunction')

    def test_document_and_common_forms_use_the_same_full_file_plan(self):
        self.add(CID,'Document',root.ID);self.xml(Path('Documents/Item.xml'),'Document',CID)
        path=self.xml(Path('Documents/Item/Forms/NewForm.xml'),'Form',FID,'NewForm')
        ext=path.with_suffix('')/'Ext';ext.mkdir(parents=True);(ext/'Form.xml').write_text('<Form/>',encoding='utf-8')
        self.assertEqual(self.plan(path)['kind'],'DocumentForm')
        self.add(FID,'DocumentForm',CID,'NewForm');self.assertEqual(self.plan(path)['operation'],'Изменение')
        self.objects.pop(FID)
        path=self.xml(Path('CommonForms/NewForm.xml'),'CommonForm',FID,'NewForm')
        ext=path.with_suffix('')/'Ext';ext.mkdir(parents=True);(ext/'Form.xml').write_text('<Form/>',encoding='utf-8')
        self.assertEqual(self.plan(path)['operation'],'Создание')
        self.add(FID,'CommonForm',root.ID,'NewForm');self.assertEqual(self.plan(path)['operation'],'Изменение')

    def test_accumulation_requires_whole_existing_recorder_xml(self):
        path=self.xml(Path('AccumulationRegisters/Item.xml'),'AccumulationRegister',FID)
        with self.assertRaisesRegex(ValueError,'recorder'):self.plan(path)
        recorder=self.xml(Path('Documents/Recorder.xml'),'Document',CID,'Recorder');self.add(CID,'Document',root.ID,'Recorder')
        plan=self.plan(path,related_xml_paths=[str(recorder)]);self.assertEqual(plan['related_objects'][0]['object_id'],CID)
        with self.assertRaisesRegex(ValueError,'identity'):self.plan(path,related_xml_paths=[str(recorder),str(recorder)])
        with self.assertRaisesRegex(ValueError,'array'):self.plan(path,related_xml_paths=str(recorder))

    def test_processor_reads_whole_module_files_and_rejects_unknown_companions(self):
        for kind,folder,names in [('DataProcessor','DataProcessors',['ObjectModule','ManagerModule']),('Catalog','Catalogs',['ObjectModule','ManagerModule']),('Document','Documents',['ObjectModule','ManagerModule']),('Enum','Enums',['ManagerModule']),('Constant','Constants',['ValueManagerModule','ManagerModule']),('DocumentJournal','DocumentJournals',['ManagerModule'])]:
            with self.subTest(kind=kind):
                path=self.xml(Path(folder)/'Item.xml',kind,CID);ext=path.with_suffix('')/'Ext';ext.mkdir(parents=True)
                sources={name:'// complete '+name if i==0 else '' for i,name in enumerate(names)}
                for name,text in sources.items():(ext/(name+'.bsl')).write_text(text,encoding='utf-8')
                self.assertEqual(self.plan(path)['modules'],sources)
                (ext/'Unknown.xml').write_text('<Lost/>',encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'companion'):self.plan(path)

    def test_command_modules_are_discovered_for_creation_and_change(self):
        for kind,folder in [('Document','Documents'),('DataProcessor','DataProcessors'),('Report','Reports')]:
            with self.subTest(kind=kind):
                self.objects.pop(CID,None)
                path=self.xml(Path(folder)/'Item.xml',kind,CID);tree=E.parse(path);q=p.Q;command=E.SubElement(E.SubElement(tree.getroot()[0],q+'ChildObjects'),q+'Command',uuid=FID);E.SubElement(E.SubElement(command,q+'Properties'),q+'Name').text='TestCommand';tree.write(path,encoding='utf-8')
                module=path.with_suffix('')/'Commands/TestCommand/Ext/CommandModule.bsl';module.parent.mkdir(parents=True);module.write_text('// full command',encoding='utf-8')
                expected=[dict(object_id=FID,source_text='// full command')]
                self.assertEqual(self.plan(path)['inline_modules'],expected)
                self.add(CID,kind,root.ID);self.assertEqual(self.plan(path)['inline_modules'],expected)

    def test_new_catalog_reads_all_referenced_forms_and_modules(self):
        path=self.xml(Path('Catalogs/Item.xml'),'Catalog',CID)
        top=E.parse(path).getroot();children=E.SubElement(top[0],p.Q+'ChildObjects');E.SubElement(children,p.Q+'Form').text='NewForm'
        path.write_text(E.tostring(top,encoding='unicode'),encoding='utf-8')
        definition=self.xml(Path('Catalogs/Item/Forms/NewForm.xml'),'Form',FID,'NewForm')
        ext=definition.with_suffix('')/'Ext';(ext/'Form').mkdir(parents=True);(ext/'Form.xml').write_text('<Form/>',encoding='utf-8')
        (ext/'Form/Module.bsl').write_text('// entire module',encoding='utf-8')
        plan=self.plan(path);self.assertEqual(plan['forms'][0]['module_text'],'// entire module');self.assertEqual(plan['forms'][0]['form_xml'],'<Form/>')
        (ext/'Form/Module.bsl').unlink();self.assertIsNone(self.plan(path)['forms'][0]['module_text'])
        # File discovery is for creation; an existing Catalog does not create forms implicitly.
        self.add(CID,'Catalog',root.ID)
        with self.assertRaisesRegex(ValueError,'creation package'):self.plan(path)
        self.objects.pop(CID)
        self.add(FID,'CatalogForm',CID,'NewForm')
        with self.assertRaisesRegex(ValueError,'mismatch'):self.plan(path)
        self.objects.pop(FID);(ext/'Form.xml').unlink()
        with self.assertRaisesRegex(ValueError,'Missing'):self.plan(path)

    def test_catalog_form_references_reject_duplicate_and_nonlocal_names(self):
        for name in ('../Escape','..','C:\\Escape'):
            path=self.xml(Path('Catalogs/Item.xml'),'Catalog',CID);top=E.parse(path).getroot()
            E.SubElement(E.SubElement(top[0],p.Q+'ChildObjects'),p.Q+'Form').text=name
            path.write_text(E.tostring(top,encoding='unicode'),encoding='utf-8')
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'reference'):self.plan(path)

    def test_deletion_needs_explicit_uuid_and_correct_parent(self):
        self.add(CID,'Catalog',root.ID);self.add(FID,'CatalogForm',CID)
        path=self.xml(Path('Catalogs/Item.xml'),'Catalog',CID)
        plan=self.plan(path,operation='Удаление',object_id=FID)
        self.assertEqual(plan['object_id'],FID);self.assertEqual(plan['parent_id'],CID)
        with self.assertRaisesRegex(ValueError,'explicit'):self.plan(path,operation='Удаление')
        self.objects[FID][0][3]=s.atom(root.ID)
        with self.assertRaisesRegex(ValueError,'another parent'):self.plan(path,operation='Удаление',object_id=FID)

    def test_deletion_dispatches_document_and_common_forms(self):
        self.add(CID,'Document',root.ID);self.add(FID,'DocumentForm',CID)
        path=self.xml(Path('Documents/Item.xml'),'Document',CID)
        self.assertEqual(self.plan(path,operation='Удаление',object_id=FID)['kind'],'DocumentForm')
        self.add(FID,'CommonForm',root.ID)
        path=self.xml(Path('Configuration.xml'),'Configuration',root.ID,'Конфигурация')
        self.assertEqual(self.plan(path,operation='Удаление',object_id=FID)['kind'],'CommonForm')

    def test_unknown_options_types_and_unsupported_operation(self):
        path=self.xml(Path('Documents/Item.xml'),'Document',CID)
        self.add(CID,'Document',root.ID)
        self.assertEqual(self.plan(path)['operation'],'Изменение')
        with self.assertRaisesRegex(ValueError,'Unknown preparation option'):self.plan(path,bogus=True)
        path.write_text('<Form/>',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'metadata object'):self.plan(path)

    def test_root_baseline_is_optional_and_type_collisions_are_rejected(self):
        path=self.xml(Path('Configuration.xml'),'Configuration',root.ID,'Конфигурация')
        self.assertIsNone(self.plan(path)['before_xml'])
        before=self.dir/'before.xml';before.write_text(path.read_text(encoding='utf-8'),encoding='utf-8')
        self.assertEqual(self.plan(path,before_xml_path=str(before))['before_xml'],before.read_text(encoding='utf-8'))
        self.add(CID,'Catalog',root.ID)
        other=self.xml(Path('Documents/Item.xml'),'Document',CID)
        with self.assertRaisesRegex(ValueError,'another repository class'):self.plan(other)


if __name__=='__main__':unittest.main()
