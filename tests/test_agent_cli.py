"""JSON CLI contracts: validation, read-only preparation and secret boundaries."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import agent_cli as cli

OID=str(uuid.uuid4()); ZERO=str(uuid.UUID(int=0))


class AgentCLITests(unittest.TestCase):
    def request(self, action, **params):return dict(schema=1,action=action,profile='lab',params=params)

    def test_commit_requires_a_plan_file_exact_hash_and_execute(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan=Path(temporary)/'plan.json';plan.write_text('{}')
            params=dict(plan_file=str(plan),approved_plan_sha256='a'*64)
            for extra in ({},dict(execute=False),dict(execute='true'),dict(execute=True,approved_plan_sha256='bad')):
                with self.subTest(extra=extra),self.assertRaises(cli.CLIError):
                    cli.validate(self.request('changes.commit',**dict(params,**extra)))
            value=cli.validate(self.request('changes.commit',execute=True,**params))
            self.assertEqual(value['params']['approved_plan_sha256'],'a'*64)

    def test_partial_workspace_contract_and_materialize_are_local(self):
        request=self.request('workspace.init',directory='partial',allow_partial=True)
        self.assertTrue(cli.validate(request)['params']['allow_partial'])
        with self.assertRaisesRegex(cli.CLIError,'boolean'):
            cli.validate(self.request('workspace.init',directory='partial',allow_partial='true'))
        request=cli.validate(self.request('workspace.materialize',baseline_id='a'*32,object_ids=[OID]))
        import partial_baseline
        with mock.patch.object(partial_baseline,'materialize',return_value=dict(captured=False,committed=False)) as materialize,\
             mock.patch.object(cli.subprocess,'run',side_effect=AssertionError('No OneScript/transport/compiler')):
            self.assertFalse(cli.backend(request,dict(cache_directory='cache'))['committed'])
        self.assertEqual(materialize.call_args.args[0]['object_ids'],[OID])
        for params in (dict(baseline_id='x',object_ids=[OID]),dict(baseline_id='a'*32,object_ids=[]),
                       dict(baseline_id='a'*32,object_ids=[OID,OID])):
            with self.assertRaises(cli.CLIError):cli.validate(self.request('workspace.materialize',**params))

    def test_materialize_can_use_a_named_profile_offline_without_password_or_oscript(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'config.json'
            profile=dict(url='tcp://localhost/repo',platform='8.5.1.1529',username='reader',
                         password_env='CRS_OFFLINE_UNSET',cache_directory='cache')
            path.write_text(json.dumps(dict(schema=1,repositories=dict(lab=profile),runtime=dict(oscript='missing.exe'))))
            with mock.patch.dict(os.environ,{},clear=True):
                result=cli.configuration(path,'lab','workspace.materialize',{})
                self.assertEqual(result['cache_directory'],str(Path(temporary)/'cache'))
                with self.assertRaisesRegex(cli.CLIError,'password'):cli.configuration(path,'lab','connect',{})

    def test_addressed_module_preparation_requires_a_baseline_hash_and_pins_target_file(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);source=folder/'Module.bsl';source.write_bytes('текст\r\n'.encode('utf-8-sig'))
            params=dict(object_id=OID,module_path='Ext/Module.bsl',source_file=str(source),output_directory=str(folder/'review'))
            with self.assertRaises(cli.CLIError):cli.validate(self.request('modules.prepare',**params))
            request=cli.validate(self.request('modules.prepare',expected_source_sha256='0'*64,**params))
            cli.load_module_source(request,{})
            self.assertEqual(request['params']['module_text'],'текст\r\n')
            source.write_text('changed',encoding='utf-8')
            result=dict(plan=dict(after_sha256=hashlib.sha256('текст\r\n'.encode('utf-8')).hexdigest()))
            with self.assertRaisesRegex(cli.CLIError,'changed during preparation'):cli.enrich(request,result,{})

    def test_profile_limits_are_validated_and_module_source_uses_profile_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);source=folder/'module.bsl';source.write_bytes(b'12345678')
            request=cli.validate(self.request('modules.prepare',object_id=OID,module_path='Ext/Module.bsl',source_file=str(source),expected_source_sha256='0'*64,output_directory=str(folder/'out')))
            with self.assertRaisesRegex(cli.CLIError,'module_bytes'):cli.load_module_source(request,dict(limits=dict(module_bytes=4)))
            cli.load_module_source(request,dict(limits=dict(module_bytes=16)))
            self.assertEqual(request['params']['module_text'],'12345678')
            exe=folder/'runtime.exe';exe.touch();config=folder/'config.json'
            settings=dict(schema=1,repositories=dict(lab=dict(url='tcp://localhost/repo',platform='8.5.1.1529',username='reader',password_env='CRS_PROFILE_TEST',limits=dict(message_bytes=1024))),runtime=dict(oscript=str(exe)))
            config.write_text(json.dumps(settings),encoding='utf-8')
            with mock.patch.dict(os.environ,CRS_PROFILE_TEST=''):
                self.assertEqual(cli.configuration(config,'lab','connect',{})['limits']['message_bytes'],1024)
                settings['repositories']['lab']['limits']['message_bytes']=True;config.write_text(json.dumps(settings),encoding='utf-8')
                with self.assertRaisesRegex(cli.CLIError,'resource limits'):cli.configuration(config,'lab','connect',{})

    def test_duplicate_keys_and_nonfinite_values_are_not_accepted(self):
        for raw in (b'{"schema":1,"schema":2}', b'{"x":NaN}', b'\xff'):
            with self.assertRaises(cli.CLIError):cli.load_json(raw)

    def test_profile_operation_timeout_is_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);exe=folder/'oscript.exe';exe.touch();config=folder/'config.json'
            profile=dict(url='tcp://localhost/repo',platform='8.5.1.1529',username='reader',password_env='CRS_PROFILE_TEST')
            settings=dict(schema=1,repositories=dict(lab=profile),runtime=dict(oscript=str(exe)))
            with mock.patch.dict(os.environ,CRS_PROFILE_TEST=''):
                for name in ('operation_timeout_seconds','compiler_timeout_seconds'):
                    for value in (3600,True,0,-1,86401,1.5,'3600'):
                        profile[name]=value;config.write_text(json.dumps(settings),encoding='utf-8')
                        if value==3600:
                            self.assertEqual(cli.configuration(config,'lab','connect',{})[name],value)
                        else:
                            with self.assertRaisesRegex(cli.CLIError,name):cli.configuration(config,'lab','connect',{})
                    del profile[name]

    def test_actions_do_not_expose_unreviewed_configuration_commit_or_capture(self):
        for action in ('commit','objects.capture','users.execute','arbitrary_method'):
            with self.assertRaises(cli.CLIError):cli.validate(self.request(action))

    def test_schema_and_unknown_params_are_strict(self):
        for request in (dict(schema=True,action='connect',profile='lab'),self.request('connect',password='secret'),self.request('objects.search',limit=True),self.request('objects.read',object_id=ZERO)):
            with self.assertRaises(cli.CLIError):cli.validate(request)

    def test_user_creation_defaults_to_read_only_and_plan_does_not_execute(self):
        r=cli.validate(self.request('users.plan',operation='create',name='bot',password_env='NOT_REQUIRED_FOR_PLAN'))
        self.assertEqual(r['params']['role'],'read_only');self.assertNotIn('execute',r['params'])

    def test_user_application_requires_explicit_execution_and_expected_state(self):
        for params in (dict(operation='delete',user_id=OID),dict(operation='delete',user_id=OID,execute=True),dict(operation='delete',user_id=OID,execute=True,expected=dict(id=OID,name='bot',role='admin',deleted='false'))):
            with self.assertRaises(cli.CLIError):cli.validate(self.request('users.apply',**params))
        expected=dict(id=OID,name='bot',role='read_only',rights='0',deleted=False)
        cli.validate(self.request('users.apply',operation='delete',user_id=OID,execute=True,expected=expected))

    def test_unknown_roles_and_password_fields_are_not_forwarded(self):
        for changes in (dict(role='administrator'),dict(password='plaintext'),dict(password_hash='hash')):
            with self.assertRaises(cli.CLIError):cli.validate(self.request('users.plan',operation='update',user_id=OID,**changes))

    def test_output_must_not_overlap_xml_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            for output in (folder,folder/'nested'):
                with self.assertRaises(cli.CLIError):cli.validate(self.request('changes.prepare',directory=str(folder),output_directory=str(output)))

    def test_search_uses_current_descriptors_full_names_and_pagination(self):
        sys.path.insert(0,str(cli.SERIALIZATION));import metadata_identifiers
        ids={v:k for k,v in metadata_identifiers.class_labels().items()};root=OID;owner=str(uuid.uuid4());form=str(uuid.uuid4());removed=str(uuid.uuid4())
        def row(oid,kind,name,parent,deleted=False):return dict(id=oid,class_id=ids[kind],name=name,parent_id=parent,owner_id=ZERO,version=5,own_version=1,deleted=deleted)
        data=dict(repository_version='v',objects=[row(root,'Configuration','Config',ZERO),row(owner,'Catalog','Products',root),row(form,'CatalogForm','ItemForm',owner),row(removed,'Catalog','OldProducts',root,True)])
        request=cli.validate(self.request('objects.search',query='products',limit=1))
        result=cli.enrich(request,data,{})
        self.assertEqual(result['total'],2);self.assertEqual(result['next_offset'],1);self.assertEqual(result['objects'][0]['full_name'],'Catalog.Products')
        request['params']['offset']=1;result=cli.enrich(request,data,{})
        self.assertEqual(result['objects'][0]['full_name'],'Catalog.Products.Form.ItemForm')

    def test_config_password_value_does_not_enter_backend_arguments_or_request_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            module=Path(temporary);config=dict(oscript=sys.executable,module_path=str(module),url='tcp://localhost:1542/test',platform='8.5.1.1529',username='reader',password_env='CLI_TEST_SECRET',python=sys.executable)
            config.update(operation_timeout_seconds=7200,compiler_timeout_seconds=3600)
            def fake(cmd,**kwargs):
                source=Path(cmd[-2]);contents=source.read_text();self.assertNotIn('VALUE-NEVER-SERIALIZE',contents)
                self.assertNotIn('VALUE-NEVER-SERIALIZE',' '.join(cmd));self.assertTrue((source.parent/'oscript.cfg').is_file())
                self.assertEqual(kwargs['env']['CLI_TEST_SECRET'],'VALUE-NEVER-SERIALIZE')
                self.assertEqual(kwargs['timeout'],7200)
                self.assertEqual(kwargs['env']['CRS_COMPILER_TIMEOUT_SECONDS'],'3600')
                Path(cmd[-1]).write_text('{"ok":true,"result":{"connected":true}}')
                return subprocess.CompletedProcess(cmd,0,b'',b'')
            with mock.patch.dict(os.environ,CLI_TEST_SECRET='VALUE-NEVER-SERIALIZE'),mock.patch.object(cli.subprocess,'run',side_effect=fake):
                self.assertTrue(cli.backend(self.request('connect'),config)['connected'])

    def test_backend_logs_or_error_xml_are_not_leaked_as_json(self):
        def fake(cmd,**kwargs):
            Path(cmd[-1]).write_text('{"ok":false,"error":{"code":"backend_error","detail":"PASSWORD-HASH-SECRET"}}')
            return subprocess.CompletedProcess(cmd,1,b'<password>PASSWORD-HASH-SECRET</password>',b'PASSWORD-HASH-SECRET')
        with tempfile.TemporaryDirectory() as temporary,mock.patch.object(cli.subprocess,'run',side_effect=fake):
            with self.assertRaises(cli.CLIError) as caught:cli.backend(self.request('connect'),dict(oscript=sys.executable,module_path=temporary))
            self.assertNotIn('PASSWORD-HASH-SECRET',str(caught.exception))

    def test_timeout_on_user_write_has_unknown_outcome(self):
        with tempfile.TemporaryDirectory() as temporary,mock.patch.object(cli.subprocess,'run',side_effect=subprocess.TimeoutExpired('oscript',600)):
            with self.assertRaises(cli.CLIError) as caught:cli.backend(self.request('users.apply'),dict(oscript=sys.executable,module_path=temporary))
            self.assertEqual(caught.exception.code,'outcome_unknown')

    def test_help_and_invalid_input_are_single_json_from_any_working_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            for args,raw,expected in [(['--help'],b'',True),(['--config','missing'],b'{"schema":true}',False),(['--unknown'],b'',False)]:
                p=subprocess.run([sys.executable,str(cli.ROOT/'tools/crs.py'),*args],input=raw,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=temporary)
                result=json.loads(p.stdout);self.assertEqual(result['ok'],expected);self.assertEqual(p.returncode,0 if expected else 1);self.assertEqual(p.stderr,b'')

    def test_onescript_defaults_and_raw_user_rights_regression(self):
        engine=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'OneScript/bin/oscript.exe'
        if not engine.is_file():self.skipTest('OneScript not installed')
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);(folder/'oscript.cfg').write_text('lib.additional='+str(cli.ROOT/'oscript_modules'),encoding='utf-8-sig')
            code=(cli.ROOT/'src/cli_bridge.os').read_text(encoding='utf-8-sig').split('\nКодОшибки = "backend_error";')[0]
            code=code.replace('#Использовать ".."','#Использовать "'+cli.ROOT.as_posix()+'"')
            code+='''
Если Значение(Новый Структура, "missing", "preserved") <> "preserved" Тогда ВызватьИсключение "Default lost"; КонецЕсли;
П = Новый ПользовательХранилища; П.Идентификатор = Новый УникальныйИдентификатор; П.Имя = "test"; П.Удален = Ложь;
П.Роль = РолиХранилища.РольИзСтроки("65535"); Д = ПользовательJSON(П);
Если Д.role <> "admin" Или Д.rights <> "65535" Тогда ВызватьИсключение "Admin rights lost"; КонецЕсли;
П.Роль = РолиХранилища.РольИзСтроки("123"); Д = ПользовательJSON(П);
Если Д.role <> "unknown" Или Д.rights <> "123" Тогда ВызватьИсключение "Unknown rights downgraded"; КонецЕсли;
Сообщить("PASS");
'''
            source=folder/'probe.os';source.write_text(code,encoding='utf-8-sig')
            p=subprocess.run([str(engine),str(source)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
            self.assertEqual(p.returncode,0,p.stdout.decode('utf-8',errors='replace'));self.assertEqual(p.stdout.strip(),b'PASS');self.assertEqual(p.stderr,b'')


if __name__=='__main__':unittest.main()
