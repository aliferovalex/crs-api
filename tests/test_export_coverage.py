"""Whole native assets cannot silently disappear from complete CF exports."""
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import cf_container
import export_coverage as coverage
import ibcmd_backend
import native_metadata as s
import native_streams

OID='11111111-1111-4111-8111-111111111111'


class ExportCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures=Path(__file__).parent/'fixtures'
        saved=json.loads((fixtures/'native_multistream_form.json').read_text(encoding='utf-8'))
        cls.form=json.loads(zlib.decompress(base64.b64decode(saved['zlib'])))
        cls.module=base64.b64decode(json.loads((fixtures/'native_module.json').read_text(encoding='utf-8'))['stream'])

    def check(self,kind,streams,files,path='Catalogs/Test.xml',node=None):
        image={OID+suffix:raw for suffix,raw in streams.items()}
        coverage.require_complete_export(image,{OID:dict(kind=kind,path=path,node=node)},files)

    def test_measured_module_container_requires_bsl_and_binary_module_requires_bin(self):
        self.assertTrue(coverage._module(self.module))
        path='Catalogs/Test/Ext/ObjectModule.bsl'
        with self.assertRaisesRegex(ValueError,'omitted native asset.*ObjectModule.bsl'):
            self.check('Catalog',{'.0':self.module},{})
        self.check('Catalog',{'.0':self.module},{path:b'exported'})
        with self.assertRaisesRegex(ValueError,'ObjectModule.bin'):
            self.check('Catalog',{'.0':b'protected'},{path:b'exported'})
        self.check('Catalog',{'.0':b'protected'},{path[:-3]+'bin':b'protected'})

    def test_native_recalculation_module_is_required_and_classified_without_property_writers(self):
        case=json.loads(Path(__file__).parent.joinpath('fixtures/native_recalculation_module.json').read_text(encoding='utf-8'))
        oid=case['object_id'];raw=base64.b64decode(case['stream']);module=base64.b64decode(case['module'])
        path=str(Path(case['path']).with_suffix('')/'Ext/RecordSetModule.bsl').replace('\\','/')
        record=dict(kind='Recalculation',path=case['path'],node=ET.fromstring(case['xml'])[0])
        self.assertEqual(native_streams.roles('Recalculation',oid,[oid+'.0',oid+'.extra']),
                         {oid+'.0':'module',oid+'.extra':'opaque'})
        self.assertEqual(coverage._module(raw).replace('\r\n','\n'),module.decode('utf-8-sig').replace('\r\n','\n'))
        coverage.require_complete_export({oid+'.0':raw},{oid:record},{path:module})
        with self.assertRaisesRegex(ValueError,'omitted native asset.*RecordSetModule.bsl'):
            coverage.require_complete_export({oid+'.0':raw},{oid:record},{})
        with self.assertRaisesRegex(ibcmd_backend.ExportMismatch,'omitted native asset.*RecordSetModule.bsl'):
            ibcmd_backend.require_complete_export({oid+'.0':raw},{oid:record},{})

    def test_known_empty_module_and_command_interface_can_be_omitted(self):
        self.check('Catalog',{'.0':b'\xef\xbb\xbf'},{})
        self.check('Subsystem',{'.1':b'{7,0,0,0,0,0,0}'},{})
        with self.assertRaisesRegex(ValueError,'CommandInterface.xml'):
            self.check('Subsystem',{'.1':b'{7,1,0,0,0,0,0}'},{})

    def test_format16_module_container_and_empty_container_text(self):
        for raw in (b'',b'Procedure Test()\nEndProcedure'):
            output=io.BytesIO();writer=cf_container.Container64();writer.file=output;writer.write_header(1)
            with tempfile.TemporaryFile() as source:
                source.write(raw);source.seek(0);writer.add_file(source,'text')
            writer.write_table_off_content()
            self.assertEqual(coverage._module(output.getvalue()),raw.decode())
            if not raw:self.check('Catalog',{'.0':output.getvalue()},{})

    def test_real_form_module_is_required_in_addition_to_interface(self):
        raw=base64.b64decode(self.form['streams'][self.form['object_id']+'.0'])
        files={'Catalogs/Test/Ext/Form.xml':b'<Form/>'}
        with self.assertRaisesRegex(ValueError,'Ext/Form/Module.bsl'):
            self.check('Form',{'.0':raw},files)
        files['Catalogs/Test/Ext/Form/Module.bsl']=b'exported'
        self.check('Form',{'.0':raw},files)
        form=coverage._group(raw);form[2]=s.atom('',True)
        files.pop('Catalogs/Test/Ext/Form/Module.bsl')
        self.check('CatalogForm',{'.0':s.native_body_bytes([form])},files)

    def test_form_interface_empty_native_fields_do_not_affect_module_detection(self):
        raw=b'{4,{59,0,,{1,2}},"Procedure Test()\nEndProcedure",0}'
        self.assertEqual(coverage._form_module(raw),'Procedure Test()\nEndProcedure')
        with self.assertRaisesRegex(ValueError,'module slot'):
            coverage._form_module(b'{4,{59,0},0,0}')

    def test_real_help_requires_index_and_every_page(self):
        raw=base64.b64decode(self.form['streams'][self.form['object_id']+'.1'])
        files={'Catalogs/Test/Ext/Help.xml':b'<Help><Page>ru</Page></Help>'}
        with self.assertRaisesRegex(ValueError,'Help/ru.html'):
            self.check('Catalog',{'.1':raw},files)
        files['Catalogs/Test/Ext/Help/ru.html']=b'html'
        self.check('Catalog',{'.1':raw},files)
        files['Catalogs/Test/Ext/Help.xml']=b'<Help/>'
        with self.assertRaisesRegex(ValueError,'Help index differs'):
            self.check('Catalog',{'.1':raw},files)

    def test_help_attachments_and_empty_help(self):
        raw=b'{5,1,"ru",{#base64:YWJj},1,"pic.png",0,{#base64:eHl6}}'
        files={'Catalogs/Test/Ext/Help.xml':b'<Help><Page>ru</Page></Help>',
               'Catalogs/Test/Ext/Help/ru.html':b'abc'}
        with self.assertRaisesRegex(ValueError,'Help/pic.png'):
            self.check('Catalog',{'.1':raw},files)
        files['Catalogs/Test/Ext/Help/pic.png']=b'xyz'
        self.check('Catalog',{'.1':raw},files)
        self.check('Catalog',{'.1':b'{5,0,0}'},{})
        with self.assertRaisesRegex(ValueError,'filename'):
            self.check('Catalog',{'.1':raw.replace(b'pic.png',b'../pic.png')},files)

    def test_configuration_paths_are_root_relative_and_opaque_assets_are_required(self):
        self.check('Configuration',{'.6':b'\xef\xbb\xbfmessage();'},{'Ext/ManagedApplicationModule.bsl':b'text'},'Configuration.xml')
        with self.assertRaisesRegex(ValueError,'Ext/ParentConfigurations.bin'):
            self.check('Configuration',{'.4':b'opaque'},{},'Configuration.xml')
        self.check('Configuration',{'.4':b'opaque'},{'Ext/ParentConfigurations.bin':b'opaque'},'Configuration.xml')

    def test_unknown_nonempty_stream_and_missing_owner_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unmapped nonempty native stream'):
            self.check('Catalog',{'.future':b'unknown'},{})
        self.check('Catalog',{'.future':b''},{})
        with self.assertRaisesRegex(ValueError,'owner is absent'):
            coverage.require_complete_export({OID+'.0':self.module},{},{})

    def test_inline_command_and_configuration_feature_own_their_streams(self):
        other='22222222-2222-4222-8222-222222222222'
        node=ET.fromstring('<Catalog xmlns="'+coverage.Q[1:-1]+'"><ChildObjects><Command uuid="'+other+'"><Properties><Name>Run</Name></Properties></Command></ChildObjects></Catalog>')
        records={OID:dict(kind='Catalog',path='Catalogs/Test.xml',node=node)}
        coverage.require_complete_export({other+'.2':self.module},records,
            {'Catalogs/Test/Commands/Run/Ext/CommandModule.bsl':b'exported'})
        node=ET.fromstring('<Configuration xmlns="'+coverage.Q[1:-1]+'" xmlns:xr="'+coverage.XR[1:-1]+'"><InternalInfo><xr:ContainedObject><xr:ClassId>'+coverage.native_configuration_reader.ROOT_FEATURE_CLASS+'</xr:ClassId><xr:ObjectId>'+other+'</xr:ObjectId></xr:ContainedObject></InternalInfo></Configuration>')
        records={OID:dict(kind='Configuration',path='Configuration.xml',node=node)}
        coverage.require_complete_export({other+'.6':self.module},records,
            {'Ext/ManagedApplicationModule.bsl':b'exported'})

    def test_picture_index_requires_its_binary_file(self):
        files={'Catalogs/Test/Ext/Picture.xml':('<ExtPicture xmlns:xr="'+coverage.XR[1:-1]+'"><xr:Abs>Picture.zip</xr:Abs></ExtPicture>').encode()}
        with self.assertRaisesRegex(ValueError,'Picture/Picture.zip'):
            self.check('CommonPicture',{'.0':b'native picture'},files)
        files['Catalogs/Test/Ext/Picture/Picture.zip']=b'zip'
        self.check('CommonPicture',{'.0':b'native picture'},files)

    def test_template_definition_selects_the_file_extension(self):
        node=ET.fromstring('<Template><TemplateType>TextDocument</TemplateType></Template>')
        with self.assertRaisesRegex(ValueError,'Template.txt'):
            self.check('Template',{'.0':b'text'},{'Catalogs/Test/Ext/Template.xml':b'wrong'},node=node)
        self.check('Template',{'.0':b'text'},{'Catalogs/Test/Ext/Template.txt':b'text'},node=node)

    def test_backend_reports_coverage_failure_as_export_mismatch(self):
        with self.assertRaises(ibcmd_backend.ExportMismatch):
            ibcmd_backend.require_complete_export({OID+'.future':b'unknown'},
                {OID:dict(kind='Catalog',path='Catalogs/Test.xml')},{})

    def test_route_map_is_unique_and_all_families_resolve(self):
        rows=native_streams._ROUTES
        self.assertEqual(len(rows),len({(row['family'],row['suffix']) for row in rows}))
        for row in rows:
            with self.subTest(family=row['family']):
                self.assertIn(row['suffix'],native_streams.routes(row['family']))


if __name__=='__main__':unittest.main()
