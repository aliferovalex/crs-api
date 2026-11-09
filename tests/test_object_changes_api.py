"""Read-only API contract: history and descriptors only, no whole CF download."""
import copy
import socket
import subprocess
import threading
import unittest
from xml.etree import ElementTree as E
from test_version_labels import ROOT, OSCRIPT, Q, END
from pathlib import Path


def objects(rows):
    root = E.Element(Q+'call_return'); group = E.SubElement(root, Q+'objects')
    for oid, name, number, removed in rows:
        row = E.SubElement(group, Q+'value'); E.SubElement(row, Q+'first', value=oid)
        info = E.SubElement(E.SubElement(row, Q+'second'), Q+'info')
        for key, value in dict(id=oid, classID='22222222-2222-4222-8222-222222222222',
                              name=name, pos='0', verNum=str(number), selfVerNum=str(number),
                              parentID='33333333-3333-4333-8333-333333333333',
                              ownerID='33333333-3333-4333-8333-333333333333',
                              original='a'*40, local='b'*40, removed=str(removed).lower()).items():
            E.SubElement(info, Q+key, value=value)
    return E.tostring(root, encoding='utf-8')


@unittest.skipUnless(OSCRIPT and Path(OSCRIPT).is_file(), 'OneScript unavailable')
class ChangesAPITests(unittest.TestCase):
    def test_changed_deleted_created_and_previous_object_version(self):
        history = E.parse(ROOT/'tests/fixtures/version_history.xml').getroot()
        versions = history.find(Q+'versions'); original = copy.deepcopy(versions[0])
        for number in [40, 41]:  # Deliberately unordered server history.
            row = copy.deepcopy(original); row.find(Q+'first').set('value', str(number))
            row.find(Q+'second/'+Q+'info/'+Q+'verNum').set('value', str(number)); versions.append(row)
        ids = ['11111111-1111-4111-8111-'+str(i)*12 for i in [1, 2, 3]]
        replies = [
            ('DevDepot_depotInfo', None, b'<crs:call_return xmlns:crs="http://v8.1c.ru/8.2/crs"><crs:ok value="true"/></crs:call_return>'),
            ('DevDepot_devDepotVersions', None, E.tostring(history)),
            ('DevDepot_versionObjects', '42', objects([(ids[0], 'New', 42, False), (ids[1], 'Removed', 42, True), (ids[2], 'Created', 42, False)])),
            ('DevDepot_versionObjects', '41', objects([(ids[1], 'Removed', 41, False)])),
            ('DevDepot_versionObjects', '40', objects([(ids[0], 'Old', 40, False)]))]
        failures = []; calls = []
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen(); listener.settimeout(10)
            def serve():
                try:
                    for method, version, response in replies:
                        connection, _ = listener.accept()
                        with connection:
                            connection.settimeout(10); connection.sendall(bytes.fromhex('53f5c61a7b')); request = b''
                            while not request.endswith(END):
                                part = connection.recv(65536)
                                if not part: raise AssertionError('Truncated RPC')
                                request += part
                            call = E.fromstring(request.split(b'\r\n\r\n', 1)[1][:-4]); calls.append(call.get('name'))
                            if call.get('name') != method: raise AssertionError('Unexpected RPC: '+str(call.get('name')))
                            if version is not None and call.find(Q+'params/'+Q+'verNum').get('value') != version:
                                raise AssertionError('Wrong historical descriptor version')
                            body = b'\xef\xbb\xbf'+response
                            connection.sendall(('HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n'%len(body)).encode()+body+END)
                            connection.recv(1)
                except BaseException as error: failures.append(error)
            worker = threading.Thread(target=serve, daemon=True); worker.start()
            result = subprocess.run([OSCRIPT, str(ROOT/'tests/check-object-changes.os'),
                                     'tcp://127.0.0.1:'+str(listener.getsockname()[1])],
                                    cwd=ROOT, capture_output=True, timeout=30)
            worker.join(12)
        self.assertFalse(worker.is_alive()); self.assertEqual(failures, [])
        self.assertEqual(result.returncode, 0, (result.stdout+result.stderr).decode('utf-8', errors='replace'))
        self.assertEqual(calls, [row[0] for row in replies])
