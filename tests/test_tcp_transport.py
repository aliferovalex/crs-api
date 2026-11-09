"""Exercise OneScript against a real socket with fragmented native CRS frames."""
import base64,os,shutil,socket,subprocess,tempfile,threading,time,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OSCRIPT=shutil.which('oscript') or (r'C:\Program Files\OneScript\bin\oscript.exe' if os.name=='nt' else None)
END=bytes.fromhex('6653b2a6')
GREETING=bytes.fromhex('53f5c61a7b')


@unittest.skipUnless(OSCRIPT and Path(OSCRIPT).is_file(),'OneScript is not installed')
class TCPTransportTests(unittest.TestCase):
    def exchange(self,mode,expected='ok'):
        request=('<?xml version="1.0" encoding="UTF-8"?><request>'+'Привет '*1500+'</request>')
        response='<answer>Ответ '+('Б'*140000)+'</answer>'
        raw=response.encode('utf-8');received=[];failures=[]
        with tempfile.TemporaryDirectory() as directory,socket.socket() as listener:
            directory=Path(directory);(directory/'request.xml').write_text(request,encoding='utf-8')
            listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(20)
            port=listener.getsockname()[1]
            def serve():
                try:
                    connection,_=listener.accept()
                    with connection:
                        connection.settimeout(15)
                        if mode=='bad_greeting':connection.sendall(b'wrong');return
                        for part in (GREETING[:1],GREETING[1:]):
                            connection.sendall(part);time.sleep(.01)
                        data=b''
                        while b'\r\n\r\n' not in data:data+=connection.recv(65536)
                        header,body=data.split(b'\r\n\r\n',1)
                        length=int(next(row.split(b':',1)[1] for row in header.split(b'\r\n') if row.lower().startswith(b'content-length:')))
                        while len(body)<length+4:
                            part=connection.recv(65536)
                            if not part:raise AssertionError('request was truncated')
                            body+=part
                        received.append(body)
                        if mode=='eof_header':connection.sendall(b'HTTP/1.1 201');return
                        if mode=='duplicate_length':
                            connection.sendall(b'HTTP/1.1 201 Created\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\n');return
                        # The native server emits an extra CR in some header lines.
                        header=('HTTP/1.1 201 Created\r\r\nContent-Length: %d\r\r\nContent-Type: application/xml\r\n\r\n'%len(raw)).encode()
                        if mode=='truncated_body':connection.sendall(header+raw[:20]);return
                        if mode=='bad_end':connection.sendall(header+raw+b'fail');return
                        if mode=='fragmented':
                            for part in (header[:3],header[3:-1],header[-1:],raw[:1],raw[1:65537],raw[65537:],END[:1],END[1:]):
                                connection.sendall(part);time.sleep(.01)
                        else:connection.sendall(header+raw+END)
                        # Completion is framed by length and marker, not by EOF.
                        connection.recv(1)
                except BaseException as error:failures.append(error)
            worker=threading.Thread(target=serve,daemon=True);worker.start()
            result=subprocess.run([OSCRIPT,str(ROOT/'tests/check-transport.os'),f'tcp://127.0.0.1:{port}',
                                   str(directory/'request.xml'),str(directory/'response.xml'),expected],
                                  cwd=ROOT,capture_output=True,timeout=20)
            worker.join(5)
            self.assertFalse(worker.is_alive(),'fake server did not finish')
            self.assertEqual(failures,[])
            self.assertEqual(result.returncode,0,(result.stdout+result.stderr).decode('utf-8',errors='replace'))
            if mode!='bad_greeting':self.assertEqual(received,[request.encode('utf-8')+END])
            if expected=='ok':self.assertEqual((directory/'response.xml').read_text(encoding='utf-8-sig'),response)

    def test_fragmented_and_coalesced_frames_preserve_utf8_and_byte_lengths(self):
        for mode in ('fragmented','coalesced'):
            with self.subTest(mode=mode):self.exchange(mode)

    def test_truncation_bad_marker_and_invalid_headers_are_not_retried(self):
        for mode,message in [('bad_greeting','приветствие'),('eof_header','до конца ответа'),
                             ('duplicate_length','Content-Length'),('truncated_body','до конца ответа'),('bad_end','конец TCP')]:
            with self.subTest(mode=mode):self.exchange(mode,message)

    def test_history_server_error_is_not_reported_as_an_empty_history(self):
        namespace='http://v8.1c.ru/8.2/crs'
        auth=('<crs:call_return xmlns:crs="'+namespace+'"><crs:ok value="true"/></crs:call_return>').encode()
        error_response=('<crs:call_exception xmlns:crs="'+namespace+'" clsid="3ccb2518-9616-4445-aaa7-20048fead174">'+
               base64.b64encode(b'history denied').decode()+'</crs:call_exception>').encode()
        failures=[]
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen(2);listener.settimeout(15)
            def serve():
                try:
                    for method,reply in [(b'DevDepot_depotInfo',auth),(b'DevDepot_devDepotVersions',error_response)]:
                        connection,_=listener.accept()
                        with connection:
                            connection.settimeout(10);connection.sendall(GREETING);request=b''
                            while not request.endswith(END):
                                part=connection.recv(65536)
                                if not part:raise AssertionError('request was truncated')
                                request+=part
                            if method not in request:raise AssertionError('unexpected method')
                            connection.sendall(('HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n'%len(reply)).encode()+reply+END)
                            connection.recv(1)
                except BaseException as error:failures.append(error)
            worker=threading.Thread(target=serve,daemon=True);worker.start()
            result=subprocess.run([OSCRIPT,str(ROOT/'tests/check-version-history.os'),
                                   'tcp://127.0.0.1:'+str(listener.getsockname()[1])],cwd=ROOT,capture_output=True,timeout=15)
            worker.join(5)
            self.assertFalse(worker.is_alive());self.assertEqual(failures,[])
            self.assertEqual(result.returncode,0,(result.stdout+result.stderr).decode('utf-8',errors='replace'))


if __name__=='__main__':unittest.main()
