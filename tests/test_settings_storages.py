"""Settings storages use common body, module and owned-form serializers."""
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree as E
import test_defined_types
import metadata_object_xml as objects
import metadata_targets
import object_xml_profiles as profiles
import native_metadata as s


class SettingsStorageTests(unittest.TestCase):
    def samples(self):
        return json.loads(Path(__file__).with_name('fixtures').joinpath('settings_storages_851.json').read_text(encoding='utf-8'))['samples']

    def test_default_and_four_form_references_match_native_bodies(self):
        for case in self.samples():
            with self.subTest(name=case['name']):
                forms={row['name']:row['id'] for row in case['forms']}
                raw=objects.create(case['xml'],'8.5.1.1529','SettingsStorage',forms)[2]
                self.assertEqual(s.render(s.Parser(raw.decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))
                exported=objects.export(s.Parser(case['body']).documents()[0],forms,'8.5.1.1529','SettingsStorage')
                self.assertEqual(objects.create(E.tostring(exported,encoding='unicode'),'8.5.1.1529','SettingsStorage',forms)[2],raw)

    def test_change_preserves_manager_type_and_rebuilds_form_references(self):
        case=self.samples()[1];root=E.fromstring(case['xml']);root[0].remove(root[0].find(objects.Q+'InternalInfo'))
        props=root[0].find(objects.Q+'Properties');props.find(objects.Q+'Comment').text='Changed storage'
        props.find(objects.Q+'DefaultSaveForm').text='SettingsStorage.ProbeStorage.Form.LoadForm';props.find(objects.Q+'AuxiliaryLoadForm').text=None
        forms={row['name']:row['id'] for row in case['forms']};targets=metadata_targets.creation('SettingsStorage',case['id'],case['name'],forms)
        source=s.Parser(case['body']).documents()[0]
        raw,_=objects.change(E.tostring(root,encoding='unicode'),'8.5.1.1529','SettingsStorage',source,reference_objects=targets)
        actual=s.Parser(raw.decode('utf-8-sig')).documents()[0]
        self.assertEqual([s.val(actual[1][i]) for i in (2,3)],[s.val(source[1][i]) for i in (2,3)])
        self.assertEqual(s.val(actual[1][5]),forms['LoadForm']);self.assertEqual(s.val(actual[1][6]),s.ZERO)

    def test_foreign_or_missing_owned_form_is_rejected(self):
        case=self.samples()[1];forms={row['name']:row['id'] for row in case['forms']}
        for text in ('SettingsStorage.Other.Form.SaveForm','SettingsStorage.ProbeStorage.Form.Missing'):
            root=E.fromstring(case['xml']);root[0].find(objects.Q+'Properties/'+objects.Q+'DefaultSaveForm').text=text
            with self.subTest(reference=text),self.assertRaises(ValueError):objects.create(E.tostring(root,encoding='unicode'),'8.5.1.1529','SettingsStorage',forms)

    def test_new_storage_forms_and_manager_module_share_configuration_packet(self):
        import test_final_native_references as cases
        import configuration_commit as commit
        import configuration_batch as batch
        helper=cases.FinalNativeReferenceTests();request,_,_,_,_=helper.case();self.addCleanup(helper.doCleanups)
        directory=Path(request['directory']);path=directory/'Configuration.xml';root=E.parse(path);children=root.getroot()[0].find(objects.Q+'ChildObjects')
        for case in self.samples():
            file=directory/case['path'];file.parent.mkdir(parents=True,exist_ok=True);file.write_text(case['xml'],encoding='utf-8');E.SubElement(children,objects.Q+'SettingsStorage').text=case['name']
            if case.get('module'):
                ext=file.with_suffix('')/'Ext';ext.mkdir(parents=True);(ext/'ManagerModule.bsl').write_bytes(case['module'].encode('utf-8'))
            for form in case['forms']:
                definition=directory/form['path'];definition.parent.mkdir(parents=True,exist_ok=True);definition.write_text(form['xml'],encoding='utf-8');ext=definition.with_suffix('')/'Ext';(ext/'Form').mkdir(parents=True)
                # The native witness has an empty interface with its own module.
                import managed_form_xml
                module=s.val(managed_form_xml.interface(form['interface'].encode('utf-8-sig'))[2])
                fq='{http://v8.1c.ru/8.3/xcf/logform}';interface=E.Element(fq+'Form',version='2.21');E.SubElement(interface,fq+'AutoCommandBar',name='FormCommandBar',id='-1');E.SubElement(interface,fq+'ChildItems');E.SubElement(interface,fq+'Attributes')
                (ext/'Form.xml').write_bytes(E.tostring(interface,encoding='utf-8'));(ext/'Form/Module.bsl').write_bytes(module.encode('utf-8'))
        root.write(path,encoding='utf-8');plan,_=commit.prepare(request);request.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
        _,records=batch.read_packet(commit.serialize(request)['data']);records={row.object_id:row for row in records}
        for case in self.samples():
            self.assertEqual(s.render(s.Parser(s.inflate(records[case['id']].body).decode('utf-8-sig')).documents()),s.render(s.Parser(case['body']).documents()))
            if case.get('module'):self.assertIn(case['id']+'.8',dict(records[case['id']].externals))
            for form in case['forms']:self.assertIn(form['id']+'.0',dict(records[form['id']].externals))
        self.assertEqual(profiles.module_files('SettingsStorage'),{'ManagerModule':'.8'})


if __name__=='__main__':unittest.main()
