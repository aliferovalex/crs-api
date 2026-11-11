"""Independent failure reports and read-only inputs in the compiler probe."""
import contextlib,importlib.util,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('ibcmd_contract_probe',ROOT/'tools/check_ibcmd_contract.py')
probe=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(probe)
backend=probe.backend
OID='11111111-1111-4111-8111-111111111111'


class CompilerContractProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.xml=self.root/'xml';self.xml.mkdir();self.exe=self.root/'ibcmd.exe';self.exe.write_bytes(b'compiler')
        self.cf=self.root/'native.cf'
        self.image={'root':OID.encode(),'version':b'version','versions':b'versions',OID:b'{0}'}
        backend.write_cf(self.cf,self.image)
        self.text=('<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses"><Configuration uuid="'+OID+'">'
                   '<Properties><Name>Probe</Name></Properties><ChildObjects/></Configuration></MetaDataObject>')
        (self.xml/'Configuration.xml').write_text(self.text,encoding='utf-8')

    def run_check(self):return probe.check(self.exe,self.cf,self.xml,'8.5.1.1529')

    def write_export(self,directory):
        Path(directory).mkdir();Path(directory,'Configuration.xml').write_text(self.text,encoding='utf-8')

    def test_export_failure_does_not_hide_independent_compilation_failure(self):
        calls=[]
        def execute(*args):
            calls.append(args[:2])
            if args[:2]==('cf','export'):raise backend.ExportMismatch('missing RecordSetModule.bsl')
            raise backend.CompilationRejected('OnRegistrationPeriod is not mapped',{'unsupported_enum'})
        with mock.patch.object(probe.compiled_graph,'TypeIndex'),mock.patch.object(backend.Compiler,'execute',side_effect=execute):
            result=self.run_check()
        self.assertEqual(calls,[('cf','export'),('cf','bootstrap')])
        self.assertFalse(result['ok']);self.assertTrue(result['inputs_unchanged'])
        self.assertEqual(result['phases']['native_export']['kind'],'export_mismatch')
        self.assertEqual(result['phases']['bootstrap']['codes'],['unsupported_enum'])
        self.assertEqual(result['inputs']['native_cf_sha256'],probe.digest(self.cf))

    def test_success_requires_both_complete_reverse_exports_and_keeps_sources_intact(self):
        original=self.cf.read_bytes();calls=[]
        def execute(*args):
            calls.append(args[:2])
            if args[:2]==('cf','export'):self.write_export(args[3])
            else:backend.write_cf(args[3],self.image)
        with mock.patch.object(probe.compiled_graph,'TypeIndex'),mock.patch.object(backend.Compiler,'execute',side_effect=execute):
            result=self.run_check()
        self.assertTrue(result['ok']);self.assertTrue(result['inputs_unchanged'])
        self.assertEqual(calls,[('cf','export'),('cf','bootstrap'),('cf','export')])
        self.assertEqual(self.cf.read_bytes(),original)
        self.assertEqual((self.xml/'Configuration.xml').read_text(encoding='utf-8'),self.text)
        self.assertEqual(list(self.xml.iterdir()),[self.xml/'Configuration.xml'])

    def test_input_mutation_is_reported_even_when_all_compiler_checks_pass(self):
        def execute(*args):
            if args[:2]==('cf','export'):self.write_export(args[3])
            else:
                backend.write_cf(args[3],self.image)
                (self.xml/'Configuration.xml').write_text(self.text+'\n',encoding='utf-8')
        with mock.patch.object(probe.compiled_graph,'TypeIndex'),mock.patch.object(backend.Compiler,'execute',side_effect=execute):
            result=self.run_check()
        self.assertTrue(all(row['ok'] for row in result['phases'].values()))
        self.assertFalse(result['inputs_unchanged']);self.assertFalse(result['ok'])

    def test_report_cannot_overwrite_an_input_or_become_a_source_file(self):
        for report in (self.cf,self.exe,self.xml/'report.json'):
            with self.subTest(report=report),mock.patch.object(probe,'check') as check,contextlib.redirect_stdout(io.StringIO()):
                code=probe.main(['--executable',str(self.exe),'--native-cf',str(self.cf),'--xml',str(self.xml),
                    '--platform','8.5.1.1529','--report',str(report)])
                self.assertEqual(code,2);check.assert_not_called()


if __name__=='__main__':unittest.main()
