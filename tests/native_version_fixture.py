"""Synthetic complete-version storage with explicit source stream identities."""
import base64,hashlib,json
from pathlib import Path
import native_metadata as s
import metadata_identifiers as ids


def storage(objects,bodies=None,streams=None):
    bodies=bodies or {};streams=streams or {};records=[];manifest=[s.atom(0),s.atom(len(objects))]
    base=json.loads(Path(__file__).with_name('fixtures').joinpath('form_rules_851.json').read_text(encoding='utf-8'))['bases']['InputField'].encode('utf-8-sig')
    for oid,docs in objects.items():
        kind=ids.class_labels().get(s.val(docs[0][2]),'');meta=s.text_bytes(docs)
        default=b'opaque source body'
        if kind in ('Template','CommonTemplate'):default=s.native_body_bytes([[s.atom(1),[s.atom(4),s.atom(0),s.atom(1)] if kind=='CommonTemplate' else [s.atom(2),s.atom(1),s.atom(0)],s.atom(0)]])
        body=s.compress(bodies.get(oid,default));records.extend([meta,body]);names=[s.val(v) for v in docs[0][11][1::2]]
        manifest.extend([s.atom(oid),s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(body).hexdigest(),True),s.atom(len(names))])
        for name in names:
            raw=streams.get(name,base if kind.endswith('Form') else b'fixture user data');data=s.compress(raw);records.append(data)
            manifest.extend([s.atom(name,True),s.atom(hashlib.sha1(data).hexdigest(),True)])
    return base64.b64encode(s.storage(records,s.text_bytes([manifest]))).decode()
