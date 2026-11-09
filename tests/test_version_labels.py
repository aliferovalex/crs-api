"""Public history API with synthetic labels, without corporate response fixtures."""
import copy
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import unittest
from xml.etree import ElementTree as E

ROOT=Path(__file__).resolve().parents[1]
OSCRIPT=shutil.which('oscript') or (r'C:\Program Files\OneScript\bin\oscript.exe' if os.name=='nt' else None)
Q='{http://v8.1c.ru/8.2/crs}'
END=bytes.fromhex('6653b2a6')


@unittest.skipUnless(OSCRIPT and Path(OSCRIPT).is_file(),'OneScript is not installed')
class VersionLabelTests(unittest.TestCase):
    def test_synthetic_model_cases(self):
        result=subprocess.run([OSCRIPT,str(ROOT/'tests/check-version-labels.os')],cwd=ROOT,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,(result.stdout+result.stderr).decode('utf-8',errors='replace'))

    def test_public_history_keeps_labels_separate_from_commit_and_configuration_version(self):
        tree=E.parse(ROOT/'tests/fixtures/version_history.xml')
        versions=tree.getroot().find(Q+'versions');original=versions[0]
        for number,names in [(43,['#DEMO-3409']),(44,['#DEMO-102','Build & "quoted"'])]:
            row=copy.deepcopy(original);row.find(Q+'first').set('value',str(number));second=row.find(Q+'second');info=second.find(Q+'info');info.find(Q+'verNum').set('value',str(number))
            if number==43:info.find(Q+'comment').text=None
            for index,name in enumerate(names):
                label=E.SubElement(second,Q+'label')
                for key,value in [('verNum',str(number)),('userID','88888888-8888-4888-8888-888888888888'),('date','2026-01-02T03:04:05'),('name',name)]:
                    E.SubElement(label,Q+key,{'value':value})
                E.SubElement(label,Q+'comment').text='Second label' if index else None
            versions.append(row)
        history=E.tostring(tree.getroot(),encoding='utf-8');auth=('<crs:call_return xmlns:crs="http://v8.1c.ru/8.2/crs"><crs:ok value="true"/></crs:call_return>').encode()
        failures=[];methods=[]
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen(2);listener.settimeout(15)
            def serve():
                try:
                    for method,reply in [('DevDepot_depotInfo',auth),('DevDepot_devDepotVersions',history)]:
                        connection,_=listener.accept()
                        with connection:
                            connection.settimeout(15);connection.sendall(bytes.fromhex('53f5c61a7b'));request=b''
                            while not request.endswith(END):
                                part=connection.recv(65536)
                                if not part:raise AssertionError('Truncated request')
                                request+=part
                            _,body=request.split(b'\r\n\r\n',1);call=E.fromstring(body[:-4]);methods.append(call.get('name'))
                            if call.get('name')!=method:raise AssertionError('Unexpected RPC method')
                            if method=='DevDepot_devDepotVersions' and call.find(Q+'params/'+Q+'filter/'+Q+'labels').get('value')!='true':raise AssertionError('Labels were not requested')
                            payload=b'\xef\xbb\xbf'+reply
                            connection.sendall(('HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n'%len(payload)).encode()+payload+END)
                            connection.recv(1)
                except BaseException as error:failures.append(error)
            worker=threading.Thread(target=serve,daemon=True);worker.start()
            result=subprocess.run([OSCRIPT,str(ROOT/'tests/check-version-labels.os'),'tcp://127.0.0.1:'+str(listener.getsockname()[1])],cwd=ROOT,capture_output=True,timeout=30)
            worker.join(5)
            self.assertFalse(worker.is_alive(),'History server did not finish')
            self.assertEqual(failures,[])
            self.assertEqual(methods,['DevDepot_depotInfo','DevDepot_devDepotVersions'])
            self.assertEqual(result.returncode,0,(result.stdout+result.stderr).decode('utf-8',errors='replace'))


if __name__=='__main__':unittest.main()
