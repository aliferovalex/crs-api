"""Historical reads preserve requested stream versions and reject incomplete replies."""
import base64
import socket
import subprocess
import sys
import threading
import unittest
import uuid
from pathlib import Path
from xml.etree import ElementTree as E
from test_version_labels import ROOT, OSCRIPT, Q, END
from test_object_changes_api import objects
from test_repository_cache import docs, snapshot, CHILD, ROOT as OWNER, OLD, NEW
import native_metadata as s


@unittest.skipUnless(OSCRIPT and Path(OSCRIPT).is_file(), 'OneScript unavailable')
class HistoricalObjectTests(unittest.TestCase):
    def run_case(self, mode):
        name = CHILD+'.0'
        description = docs(CHILD, OWNER, streams={name: OLD})
        description[0][5] = s.atom(42); description[0][6] = s.atom(12)
        if mode == 'hash': description[0][7] = s.atom(NEW)
        initial = snapshot(CHILD, description, b'body')
        complete = snapshot(CHILD, description, b'body', {name: b'historical module'})
        descriptors = E.fromstring(objects([(CHILD, 'Object', 42, False)]))
        info = descriptors.find('.//'+Q+'info')
        info.find(Q+'classID').set('value', s.val(description[0][2]))
        info.find(Q+'selfVerNum').set('value', '12')
        for key in ('original', 'local'):
            info.find(Q+key).set('value', uuid.UUID(OLD).bytes_le.hex()+'00000000')
        def payload(encoded):
            root = E.Element(Q+'call_return'); snapshots = E.SubElement(root, Q+'snapshots')
            E.SubElement(snapshots, Q+'data').text = encoded
            return E.tostring(root)
        auth = b'<crs:call_return xmlns:crs="http://v8.1c.ru/8.2/crs"><crs:ok value="true"/></crs:call_return>'
        latest = ('<crs:call_return xmlns:crs="http://v8.1c.ru/8.2/crs"><crs:verID value="'+NEW+'"/></crs:call_return>').encode()
        replies = [('DevDepot_depotInfo', auth), ('DevDepot_versionObjects', E.tostring(descriptors)),
                   ('DevDepot_latestVerID', latest), ('DevDepot_updateObjects', payload(initial))]
        if mode != 'hash': replies.append(('DevDepot_updateObjects', payload(initial if mode == 'missing' else complete)))
        failures = []; reads = []
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen(); listener.settimeout(15)
            def serve():
                try:
                    for method, reply in replies:
                        connection, _ = listener.accept()
                        with connection:
                            connection.settimeout(15); connection.sendall(bytes.fromhex('53f5c61a7b')); request = b''
                            while not request.endswith(END):
                                part = connection.recv(65536)
                                if not part: raise AssertionError('Truncated RPC')
                                request += part
                            call = E.fromstring(request.split(b'\r\n\r\n', 1)[1][:-4])
                            if call.get('name') != method: raise AssertionError('Unexpected RPC')
                            if method == 'DevDepot_updateObjects':
                                params = call.find(Q+'params'); changes = params.find(Q+'changes/'+Q+'value/'+Q+'second')
                                self.assertEqual(params.find(Q+'clientVerID').get('value'), NEW)
                                self.assertEqual(changes.find(Q+'_super/'+Q+'verNum').get('value'), '42')
                                self.assertEqual(changes.find(Q+'_super/'+Q+'selfVerNum').get('value'), '12')
                                requested = params.find(Q+'requested/'+Q+'value/'+Q+'second')
                                self.assertEqual(requested.find(Q+'verNum').get('value'), '-1')
                                external = changes.find(Q+'externals')
                                if reads:
                                    self.assertEqual(external.find(Q+'value/'+Q+'first').get('value'), name)
                                    self.assertEqual(external.find('.//'+Q+'verID').get('value'), uuid.UUID(OLD).bytes_le.hex()+'00000000')
                                else: self.assertEqual(len(external), 0)
                                reads.append(method)
                            raw = b'\xef\xbb\xbf'+reply
                            connection.sendall(('HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n'%len(raw)).encode()+raw+END)
                            connection.recv(1)
                except BaseException as error: failures.append(error)
            worker = threading.Thread(target=serve, daemon=True); worker.start()
            result = subprocess.run([OSCRIPT, str(ROOT/'tests/check-historical-object.os'),
                                     'tcp://127.0.0.1:'+str(listener.getsockname()[1]), sys.executable, mode],
                                    cwd=ROOT, capture_output=True, timeout=40)
            worker.join(16)
        self.assertFalse(worker.is_alive()); self.assertEqual(failures, [])
        self.assertEqual(result.returncode, 0, (result.stdout+result.stderr).decode('utf-8', errors='replace'))
        self.assertEqual(len(reads), 1 if mode == 'hash' else 2)

    def test_historical_streams_are_requested_with_their_own_versions(self): self.run_case('success')
    def test_missing_historical_stream_is_rejected(self): self.run_case('missing')
    def test_hash_mismatch_is_rejected_before_external_read(self): self.run_case('hash')
