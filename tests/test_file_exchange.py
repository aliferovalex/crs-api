"""File-backed version responses: framing, streaming base64 and policy boundaries."""
import base64
import hashlib
import http.server
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/Сериализация'))
import external_data
import file_exchange as exchange
import native_metadata as s
from native_storage_file import FileStorage,write
import resource_limits as limits
from test_repository_cache import CHILD,ROOT,OLD,docs,snapshot


class FileExchangeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.work=Path(self.temp.name)
        self.binary=base64.b64decode(snapshot(CHILD,docs(CHILD,ROOT,streams={CHILD+'.0':OLD}),b'body',{CHILD+'.0':b'data'}))
        self.xml=self.work/'response.xml';self.output=self.work/'result.bin'

    def xml_bytes(self,data=None,tail=''):
        return ('<crs:call_return xmlns:crs="'+exchange.NS+'"><crs:result><crs:file>'+base64.b64encode(self.binary if data is None else data).decode()+'</crs:file></crs:result>'+tail+'</crs:call_return>').encode()

    def test_rpc_trace_identifies_oversized_response_without_reading_body_or_secrets(self):
        request=self.work/'request.xml';trace=self.work/'trace.jsonl'
        request.write_text('<crs:call xmlns:crs="'+exchange.NS+'" name="DevDepot_updateObjects" alias="private-alias"><crs:auth user="private-user" password="private-hash"/><crs:data>private-body</crs:data></crs:call>')
        errors=[]
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen(1)
            def serve():
                try:
                    conn,_=listener.accept()
                    with conn:
                        conn.settimeout(5);conn.sendall(bytes.fromhex('53f5c61a7b'));data=b''
                        while not data.endswith(exchange.END):data+=conn.recv(65536)
                        conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 2087878948\r\n\r\n')
                except BaseException as error:errors.append(error)
            worker=threading.Thread(target=serve,daemon=True);worker.start()
            with mock.patch.dict(os.environ,CRS_RPC_TRACE=str(trace)),self.assertRaisesRegex(ValueError,'RPC DevDepot_updateObjects: Response Content-Length 2087878948'):
                exchange.receive('tcp://127.0.0.1:'+str(listener.getsockname()[1]),request,self.output)
            worker.join(5)
        self.assertEqual(errors,[]);self.assertFalse(self.output.exists())
        row=json.loads(trace.read_text());self.assertEqual(row['rpc'],'DevDepot_updateObjects')
        self.assertEqual(row['content_length'],2087878948);self.assertEqual(row['received_bytes'],0)
        self.assertEqual(row['outcome'],'failed');self.assertNotIn('private-',trace.read_text())

    def test_trace_failure_never_masks_transport_result_and_ignores_payload(self):
        path=self.work/'request.xml';path.write_bytes(('<crs:call xmlns:crs="'+exchange.NS+'" name="DevDepot_latestVerID"><not-xml').encode())
        self.assertEqual(exchange.request_method(path),'DevDepot_latestVerID')
        with mock.patch.dict(os.environ,CRS_RPC_TRACE=str(self.work/'missing/trace.jsonl')):
            exchange.trace_rpc(dict(rpc='DevDepot_latestVerID',outcome='received'))

    def test_streaming_decode_matches_bytes_and_accepts_split_base64_quads(self):
        self.xml.write_bytes(self.xml_bytes())
        with mock.patch.object(exchange,'CHUNK',7):result=exchange.extract_version(self.xml,self.output)
        self.assertEqual(self.output.read_bytes(),self.binary)
        self.assertEqual(result['sha256'],hashlib.sha256(self.binary).hexdigest())
        self.assertEqual(external_data.extract(FileStorage(self.output),CHILD),external_data.extract(self.binary,CHILD))

    def test_native_depot_version_info_envelope(self):
        self.xml.write_bytes(self.xml_bytes().replace(b'crs:result',b'crs:info'))
        exchange.extract_version(self.xml,self.output)
        self.assertEqual(self.output.read_bytes(),self.binary)

    def test_context_direct_file_envelope_is_distinct_from_full_version(self):
        raw=self.xml_bytes().replace(b'<crs:result>',b'<crs:info/>').replace(b'</crs:result>',b'')
        self.xml.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'file element'):exchange.extract_version(self.xml,self.output)
        exchange.extract_context(self.xml,self.output)
        self.assertEqual(self.output.read_bytes(),self.binary)
        self.output.unlink()
        self.xml.write_bytes(raw.replace(b'</crs:call_return>',b'<crs:exc>ZXJyb3I=</crs:exc></crs:call_return>'))
        with self.assertRaisesRegex(ValueError,'exception'):exchange.extract_context(self.xml,self.output)
        self.assertFalse(self.output.exists())

    def test_wrapped_base64_is_decoded_in_bounded_blocks_not_per_line(self):
        binary=s.storage([b'x'*200000],s.text_bytes([s.atom(0)]))
        encoded=base64.b64encode(binary)
        wrapped=b'\r\n'.join(encoded[pos:pos+76] for pos in range(0,len(encoded),76))
        self.xml.write_bytes(self.xml_bytes(binary).replace(encoded,wrapped))
        with mock.patch.object(exchange.base64,'b64decode',wraps=base64.b64decode) as decoder:
            exchange.extract_version(self.xml,self.output)
        self.assertEqual(self.output.read_bytes(),binary)
        self.assertLess(decoder.call_count,20)

    def test_late_exception_duplicate_file_entities_truncation_and_invalid_padding_leave_no_file(self):
        valid=self.xml_bytes()
        cases=[self.xml_bytes(tail='<crs:exc>ZXJyb3I=</crs:exc>'),valid.replace(b'</crs:result>',b'<crs:file>YQ==</crs:file></crs:result>'),
               b'<!DOCTYPE x [<!ENTITY a "x">]>'+valid,valid[:-4],valid.replace(base64.b64encode(self.binary),b'YQ==Yg=='),self.xml_bytes(b'bad storage')]
        for raw in cases:
            self.xml.write_bytes(raw)
            with self.subTest(raw=raw[-30:]),self.assertRaises(ValueError):exchange.extract_version(self.xml,self.output)
            self.assertFalse(self.output.exists())
            self.assertFalse(list(self.work.glob('*.tmp')))

    def test_limits_are_checked_for_xml_decoded_storage_and_individual_records(self):
        self.xml.write_bytes(self.xml_bytes())
        for policy in (dict(message_bytes=10),dict(storage_bytes=10),dict(record_bytes=10)):
            with limits.scope(policy),self.assertRaises(ValueError):exchange.extract_version(self.xml,self.output)
            self.assertFalse(self.output.exists())

    def test_existing_files_are_never_overwritten_or_removed(self):
        self.xml.write_bytes(self.xml_bytes());self.output.write_bytes(b'')
        with self.assertRaises((ValueError,FileExistsError)):exchange.extract_version(self.xml,self.output)
        self.assertEqual(self.output.read_bytes(),b'')
        with self.assertRaises(FileExistsError):exchange.receive('tcp://127.0.0.1:1',self.xml,self.output)
        self.assertEqual(self.output.read_bytes(),b'')

    def test_file_writer_is_byte_identical_to_storage_and_detects_post_validation_change(self):
        payloads,manifest=external_data.records(self.binary)
        records=list(payloads.values());m=s.text_bytes([manifest])
        write(self.output,iter(records),m)
        expected=s.storage(records,m)
        self.assertEqual(self.output.read_bytes(),expected)
        reader=FileStorage(self.output);key=next(iter(reader))
        offset,length=reader.entries[key]
        with self.output.open('r+b') as target:target.seek(offset);target.write(b'X')
        with self.assertRaisesRegex(ValueError,'changed'):reader[key]
        with self.assertRaisesRegex(ValueError,'checksum'):FileStorage(self.output)

    def test_tcp_file_receive_checks_end_marker_and_does_not_retry(self):
        request=self.work/'request.xml';request.write_bytes(b'<request/>')
        for marker in (exchange.END,b'fail'):
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));listener.listen(1);port=listener.getsockname()[1]
                def serve():
                    conn,_=listener.accept()
                    with conn:
                        conn.sendall(bytes.fromhex('53f5c61a7b'));raw=b''
                        while not raw.endswith(exchange.END):raw+=conn.recv(65536)
                        body=self.xml_bytes();conn.sendall(('HTTP/1.1 200 OK\r\nContent-Length: '+str(len(body))+'\r\n\r\n').encode()+body+marker)
                thread=threading.Thread(target=serve,daemon=True);thread.start()
                args=dict(url='tcp://127.0.0.1:'+str(port),request_file=str(request),output_file=str(self.output),mode='version')
                if marker==exchange.END:
                    result=exchange.run(args);self.assertEqual(self.output.read_bytes(),self.binary);self.output.unlink()
                else:
                    with self.assertRaisesRegex(ValueError,'end marker'):exchange.run(args)
                    self.assertFalse(self.output.exists())
                thread.join(5);self.assertFalse(thread.is_alive())

    def test_tcp_large_content_length_reports_exact_size_before_body(self):
        request=self.work/'request.xml';request.write_bytes(b'<request/>')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen(1);port=listener.getsockname()[1]
            def serve():
                conn,_=listener.accept()
                with conn:
                    conn.sendall(bytes.fromhex('53f5c61a7b'));raw=b''
                    while not raw.endswith(exchange.END):raw+=conn.recv(65536)
                    conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 4639121818\r\n\r\n')
            thread=threading.Thread(target=serve,daemon=True);thread.start()
            try:
                with limits.scope(dict(message_bytes=2147483648)),self.assertRaisesRegex(ValueError,'4639121818 exceeds message_bytes 2147483648'):
                    exchange.receive('tcp://127.0.0.1:'+str(port),request,self.output)
                self.assertFalse(self.output.exists())
            finally:thread.join(5)
            self.assertFalse(thread.is_alive())

    def test_http_chunked_file_receive_enforces_actual_length_budget(self):
        body=self.xml_bytes();request=self.work/'request.xml';request.write_bytes(b'<request/>')
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(handler):
                handler.rfile.read(int(handler.headers['Content-Length']));handler.send_response(200);handler.send_header('Transfer-Encoding','chunked');handler.end_headers()
                try:
                    for start in range(0,len(body),13):
                        part=body[start:start+13];handler.wfile.write(('%x\r\n'%len(part)).encode()+part+b'\r\n')
                    handler.wfile.write(b'0\r\n\r\n')
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
            def log_message(*args):pass
        with http.server.HTTPServer(('127.0.0.1',0),Handler) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                args=dict(url='http://127.0.0.1:'+str(server.server_port),request_file=str(request),output_file=str(self.output),mode='version')
                exchange.run(args);self.assertEqual(self.output.read_bytes(),self.binary);self.output.unlink()
                with limits.scope(dict(message_bytes=32)),self.assertRaisesRegex(ValueError,'byte limit'):exchange.run(args)
                self.assertFalse(self.output.exists())
            finally:server.shutdown();thread.join(5)

    def test_policy_defaults_validation_and_scopes_do_not_leak(self):
        with mock.patch.dict(os.environ,{},clear=True):
            self.assertEqual(limits.get('message_bytes'),256*1024*1024)
            for value in (True,0,-1,1.5,'32'):
                with self.assertRaises(ValueError):limits.validate(dict(message_bytes=value))
            with self.assertRaises(ValueError):limits.validate(dict(unlimited=True))
            with self.assertRaises(ValueError):limits.parse('{"message_bytes":1,"message_bytes":2}')
            with limits.scope(dict(message_bytes=17)):self.assertEqual(limits.get('message_bytes'),17)
            self.assertEqual(limits.get('message_bytes'),256*1024*1024)
            path=self.work/'limits.json';path.write_text('{"message_bytes":19}',encoding='utf-8')
            with mock.patch.dict(os.environ,CRS_LIMITS_FILE=str(path)):self.assertEqual(limits.get('message_bytes'),19)

    def test_configurable_native_cf_and_export_budgets_are_distinct(self):
        import ibcmd_backend,configuration_export
        with limits.scope(dict(storage_bytes=16)),self.assertRaises(ValueError):s.decode_storage(base64.b64encode(self.binary).decode())
        with limits.scope(dict(record_bytes=3)),self.assertRaises(ValueError):s.inflate(s.compress(b'four'))
        cf=self.work/'base.cf'
        ibcmd_backend.write_cf(cf,dict(root=b'r',version=b'v',versions=b'vs'))
        with limits.scope(dict(cf_bytes=1)),self.assertRaises(ValueError):ibcmd_backend.read_cf(cf)
        with limits.scope(dict(image_bytes=1)),self.assertRaises(ValueError):ibcmd_backend.read_cf(cf)
        export=self.work/'export';export.mkdir();(export/'asset.bin').write_bytes(b'oversized')
        with limits.scope(dict(export_file_bytes=1)),mock.patch.object(Path,'read_bytes',side_effect=AssertionError('must reject before reading')),self.assertRaises(ValueError):
            configuration_export.inventory(export)
        (export/'other.bin').write_bytes(b'other')
        with limits.scope(dict(export_files=1)),self.assertRaisesRegex(ValueError,'export_files'):
            configuration_export.inventory(export)

    @unittest.skipUnless(shutil.which('oscript') or Path('C:/Program Files/OneScript/bin/oscript.exe').is_file(),'OneScript unavailable')
    def test_onescript_uses_same_policy_and_does_not_cache_failed_validation(self):
        root=Path(__file__).resolve().parents[1]
        entry=self.work/'limits.os'
        entry.write_text('#Использовать "'+root.as_posix()+'"\n'+'''
Если АргументыКоманднойСтроки[0] = "valid" Тогда
 Если ТранспортХранилища.МаксимальныйРазмерСообщения() <> 17 Тогда ВызватьИсключение "Wrong policy value"; КонецЕсли;
 Если ОграниченияДанных.Значение("export_files", 65536) <> 2 Тогда ВызватьИсключение "Wrong file count policy"; КонецЕсли;
 Для Индекс = 1 По 2 Цикл
  Отказ = Ложь; Попытка ТранспортХранилища.ПроверитьРазмерСообщения(18); Исключение Отказ = Истина; КонецПопытки;
  Если Не Отказ Тогда ВызватьИсключение "Transport ignored policy"; КонецЕсли;
 КонецЦикла;
Иначе
 Для Индекс = 1 По 2 Цикл
  Отказ = Ложь; Попытка ТранспортХранилища.МаксимальныйРазмерСообщения(); Исключение Отказ = Истина; КонецПопытки;
  Если Не Отказ Тогда ВызватьИсключение "Invalid policy fell back to defaults"; КонецЕсли;
 КонецЦикла;
КонецЕсли;
''',encoding='utf-8-sig')
        (self.work/'oscript.cfg').write_text('lib.additional='+str(root/'oscript_modules'),encoding='utf-8-sig')
        exe=shutil.which('oscript') or 'C:/Program Files/OneScript/bin/oscript.exe'
        for policy,mode in [(dict(message_bytes=17,export_files=2),'valid'),(dict(message_bytes=0),'invalid'),(dict(unknown=17),'invalid')]:
            done=subprocess.run([exe,str(entry),mode],env=dict(os.environ,CRS_LIMITS_JSON=json.dumps(policy)),capture_output=True,timeout=30)
            self.assertEqual(done.returncode,0,(done.stdout+done.stderr).decode('utf-8',errors='replace'))

    @unittest.skipUnless(shutil.which('oscript') or Path('C:/Program Files/OneScript/bin/oscript.exe').is_file(),'OneScript unavailable')
    def test_legacy_onescript_http_checks_received_bytes_and_retains_readable_response(self):
        root=Path(__file__).resolve().parents[1];body='<answer>Ответ сервера</answer>'.encode('utf-8')
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(handler):
                handler.rfile.read(int(handler.headers['Content-Length']));handler.send_response(201)
                handler.send_header('Content-Length',str(len(body)));handler.send_header('Content-Type','application/xml; charset=utf-8');handler.end_headers();handler.wfile.write(body)
            def log_message(*args):pass
        request=self.work/'request.xml';request.write_bytes(b'<r/>')
        entry=self.work/'check.os';entry.write_text((root/'tests/check-transport.os').read_text(encoding='utf-8-sig').replace('#Использовать ".."','#Использовать "'+root.as_posix()+'"',1),encoding='utf-8-sig')
        (self.work/'oscript.cfg').write_text('lib.additional='+str(root/'oscript_modules'),encoding='utf-8-sig')
        exe=shutil.which('oscript') or 'C:/Program Files/OneScript/bin/oscript.exe'
        with http.server.HTTPServer(('127.0.0.1',0),Handler) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                for policy,mode in [(dict(),'ok'),(dict(message_bytes=17),'message_bytes')]:
                    env=dict(os.environ,CRS_LIMITS_JSON=json.dumps(policy));env.pop('CRS_IO_PYTHON',None)
                    done=subprocess.run([exe,str(entry),'http://127.0.0.1:'+str(server.server_port),str(request),str(self.work/'text.xml'),mode],env=env,capture_output=True,timeout=30)
                    self.assertEqual(done.returncode,0,(done.stdout+done.stderr).decode('utf-8',errors='replace'))
                self.assertEqual((self.work/'text.xml').read_text(encoding='utf-8-sig'),body.decode('utf-8'))
            finally:server.shutdown();thread.join(5)


if __name__=='__main__':unittest.main()
