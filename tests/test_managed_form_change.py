"""Current-version external streams, field insertion and corruption guards."""
import base64,copy,hashlib,json,struct,unittest,uuid
from pathlib import Path
from xml.etree import ElementTree as E
import test_catalog_attribute_serializer as attributes
import catalog_change_serializer
import metadata_serializer as s
import metadata_identifiers as ids
import external_data
import managed_form_change

FID='77777777-7777-4777-8777-777777777777'
EXT='88888888-8888-4888-8888-888888888888'
VER='99999999-9999-4999-8999-999999999999'


def fixture():
    r=attributes.fixture();created=catalog_change_serializer.serialize(r)
    call=E.fromstring(created['request_xml']);raw=s.inflate(base64.b64decode(call.find('{%s}params/{%s}data'%(s.NS,s.NS)).text)[18:])
    _,pos=s.read_record(raw,0);storage,pos=s.read_record(raw,pos+4);meta,pos=s.read_record(storage,12);owner_data,pos=s.read_record(storage,pos)
    owner=s.Parser(meta.decode('utf-8-sig')).documents();m=owner[0];m[0]=s.atom(5);m[5]=m[6]=s.atom(1)
    for i in (7,8):m[i]=s.atom(str(uuid.UUID(bytes_le=base64.b64decode(s.val(m[i]))[:16])))
    parent=s.val(m[1]);body=s.Parser(s.inflate(owner_data).decode('utf-8-sig')).documents()[0]
    layout=json.loads(Path(s.__file__).with_name('catalog_form_layout_851.json').read_text(encoding='utf-8'))
    form=s.Parser(layout['body_template']).documents();form[0][1][1][1][1][2]=s.atom(FID);form[0][1][1][1][2]=s.atom('Form',True)
    form_data=s.compress(s.native_body_bytes(form));external=s.compress(b'\xef\xbb\xbf'+layout['external_template'].replace('${catalog_object_type}',s.val(body[1][1])).encode('utf-8'))
    fm=[s.atom(5),s.atom(FID),s.atom(ids.class_id('CatalogForm')),s.atom(parent),s.atom(s.ZERO),s.atom(1),s.atom(1),s.atom(VER),s.atom(VER),s.atom('Form',True),s.atom(0),
        [s.atom(1),s.atom(FID+'.0',True),s.atom(EXT)],[s.atom(0)],[s.atom(0)],[s.atom(1),s.atom(parent),s.atom(1)],s.atom('Form',True),s.atom(0)]
    docs=[fm,copy.deepcopy(owner[1]),[s.atom(0)]];meta=s.text_bytes(docs)
    manifest=s.text_bytes([[s.atom(0),s.atom(1),s.atom(FID),s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(form_data).hexdigest(),True),s.atom(0)]])
    snapshot=s.storage([meta,form_data],manifest);docs[2]=[s.atom(1),[s.atom(FID+'.0',True),s.atom(EXT),s.atom(1)]]
    context=s.storage([s.text_bytes(docs)],s.text_bytes([[s.atom(0)]]))
    docs[2][1][2]=s.atom(0);form_meta=s.text_bytes(docs);owner_meta=s.text_bytes(owner)
    manifest=s.text_bytes([[s.atom(0),s.atom(2),s.atom(parent),s.atom(hashlib.sha1(owner_meta).hexdigest(),True),s.atom(hashlib.sha1(owner_data).hexdigest(),True),s.atom(0),
        s.atom(FID),s.atom(hashlib.sha1(form_meta).hexdigest(),True),s.atom(hashlib.sha1(form_data).hexdigest(),True),s.atom(1),s.atom(FID+'.0',True),s.atom(hashlib.sha1(external).hexdigest(),True)]])
    storage=s.storage([owner_meta,owner_data,form_meta,form_data,external],manifest)
    return dict(platform='8.5.1.1529',object_id=FID,original_version=uuid.UUID(VER).bytes_le.hex()+'00000000',
        snapshot=base64.b64encode(snapshot).decode(),context=base64.b64encode(context).decode(),storage=base64.b64encode(storage).decode(),attribute_name='TestAttribute')


class FormChangeTests(unittest.TestCase):
    def test_reads_current_external_and_appends_field(self):
        r=fixture();old=external_data.extract(base64.b64decode(r['storage']),FID);self.assertEqual(len(old['externals']),1)
        result=managed_form_change.serialize(r);raw=s.inflate(base64.b64decode(result['data'])[18:]);_,pos=s.read_record(raw,0);storage,pos=s.read_record(raw,pos+4);s.validate_storage(storage)
        meta,pos=s.read_record(storage,12);body,pos=s.read_record(storage,pos);extra,pos=s.read_record(storage,pos)
        new=s.Parser(s.inflate(extra).decode('utf-8-sig')).documents()[0];previous=s.Parser(s.inflate(base64.b64decode(old['externals'][0]['data'])).decode('utf-8-sig')).documents()[0]
        index=23 if not isinstance(previous[1][23],list) and s.val(previous[1][23])=='2' else 25
        self.assertEqual(s.val(new[1][index]),'3');self.assertEqual(s.val(new[1][index+6][6]),'TestAttribute')
        self.assertEqual(s.render(previous[1][index+2]),s.render(new[1][index+2]));self.assertEqual(s.render(previous[1][index+4]),s.render(new[1][index+4]))
        self.assertEqual(s.render(previous[3]),s.render(new[3]));self.assertEqual(result['object_id'],FID)
        source=base64.b64decode(r['snapshot']);_,pos=s.read_record(source,12);original,pos=s.read_record(source,pos);self.assertEqual(body,original)

    def test_stale_corrupt_and_missing_attribute(self):
        r=fixture()
        for key,value in [('original_version','f'*40),('attribute_name','Missing'),('attribute_name','bad name'),('platform','8.5.4.1878')]:
            with self.subTest(key=key),self.assertRaises(ValueError):managed_form_change.serialize(dict(r,**{key:value}))
        data=bytearray(base64.b64decode(r['storage']));data[50]^=1
        with self.assertRaises(ValueError):external_data.extract(bytes(data),FID)
        with self.assertRaises(ValueError):external_data.extract(base64.b64decode(r['storage']),str(uuid.uuid4()))

    def test_native_duplicate_records_are_indexed_separately(self):
        records=[b'same',b'same'];manifest=s.text_bytes([[s.atom(0),s.atom(0)]]);records.append(manifest)
        data=bytearray(struct.pack('<III',0x11223344,2,len(records)));entries=[]
        for payload in records:
            entries.append((hashlib.sha1(payload).digest(),len(data)));data+=s.record(payload)
        index=bytes.fromhex('11223344')+struct.pack('<II',2,len(records))
        for digest,offset in sorted(entries):index+=digest+struct.pack('<Q',offset)
        index+=bytes(20);index+=hashlib.sha1(index).digest();data+=s.record(index)
        data+=struct.pack('<Q',len(index)+8+64)+hashlib.sha1(manifest).digest()+s.EOF_MARKER;data+=hashlib.sha1(data).digest()
        payloads,parsed=external_data.records(bytes(data));self.assertEqual(len(payloads),2)
        with self.assertRaises(ValueError):s.validate_storage(bytes(data))


if __name__=='__main__':unittest.main()
