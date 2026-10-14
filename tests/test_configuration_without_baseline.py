"""Root XML uses the current native snapshot instead of a prior XML export."""
import base64, copy, hashlib, json, sys, unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import metadata_serializer as s
import test_metadata_serializer as fixtures


class WithoutBaselineTests(unittest.TestCase):
    def request(self):
        r,raw=fixtures.property_fixture('8.5.1.1529')
        r.pop('before_xml')
        r['after_xml']=r['after_xml'].replace('<Comment>До</Comment>','<Comment>Target</Comment>')
        return r,raw

    def test_same_body_with_and_without_prior_xml(self):
        r,raw=self.request()
        _,actual=s.serialize(r)
        r['before_xml']=fixtures.property_fixture('8.5.1.1529')[0]['before_xml']
        _,expected=s.serialize(r)
        self.assertEqual(actual,expected)
        self.assertEqual(actual,raw.replace('"До"'.encode(),'"Target"'.encode(),1))

    def test_invalid_target_is_rejected(self):
        r,_=self.request()
        for xml in (r['after_xml'].replace('uuid="'+fixtures.ID+'"','uuid="'+s.ZERO+'"'),
                    r['after_xml'].replace('<Vendor>','<Vendor bad="1">'),
                    r['after_xml'].replace('</Properties>','<Bogus/></Properties>'),
                    '<!DOCTYPE x>'+r['after_xml'],
                    r['after_xml'].replace('Конфигурация','Renamed'),
                    r['after_xml'].replace('</Properties>','<Vendor/></Properties>')):
            with self.subTest(xml=xml),self.assertRaises(ValueError):s.serialize(dict(r,after_xml=xml))

    def test_verified_unmapped_property_and_native_guard(self):
        r,raw=self.request();docs=s.Parser(raw.decode('utf-8-sig')).documents()
        props=s.configuration_properties(docs,'8.5.1.1529')
        profile=json.loads(Path(s.__file__).with_name('configuration_profile_851.json').read_text(encoding='utf-8'))
        for i,value in profile['native_slots'].items():props[int(i)]=s.Parser(value).documents()[0]
        def snapshot():
            meta,_=s.read_record(base64.b64decode(r['snapshot']),12)
            data=s.compress(s.text_bytes(docs))
            manifest=s.text_bytes([[s.atom(0),s.atom(1),s.atom(fixtures.ID),s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(data).hexdigest(),True),s.atom(0)]])
            r['snapshot']=base64.b64encode(s.storage([meta,data],manifest)).decode()
        target=E.fromstring(r['after_xml']);target[0].remove(target[0].find('InternalInfo'));p=target.find('.//Properties')
        E.SubElement(p,'{http://v8.1c.ru/8.3/MDClasses}DefaultRunMode').text='ManagedApplication'
        r['after_xml']=E.tostring(target,encoding='unicode');snapshot();s.serialize(r)
        props[3]=s.atom(0);snapshot()
        with self.assertRaisesRegex(ValueError,'native profile'):s.serialize(r)
        props[3]=s.atom(1);snapshot();p[-1].text='OrdinaryApplication'
        with self.assertRaisesRegex(ValueError,'DefaultRunMode'):s.serialize(dict(r,after_xml=E.tostring(target,encoding='unicode')))

    def test_no_changes(self):
        r,_=self.request();r['after_xml']=r['after_xml'].replace('Target','До')
        with self.assertRaisesRegex(ValueError,'have not changed'):s.serialize(r)

    def test_comment_uses_common_converter_with_or_without_baseline(self):
        r,_=self.request()
        _,properties=s.serialize(r)
        r['mode']='comment'
        _,comment=s.serialize(r)
        self.assertEqual(comment,properties)
        r['before_xml']=fixtures.property_fixture('8.5.1.1529')[0]['before_xml']
        _,legacy=s.serialize(r)
        self.assertEqual(legacy,comment)
        # The compatibility wrapper retains its comment-only contract.
        for baseline in (r['before_xml'],None):
            changed=dict(r,before_xml=baseline,after_xml=r['after_xml'].replace('Тест','Another vendor'))
            with self.subTest(baseline=baseline),self.assertRaisesRegex(ValueError,'Unsupported XML changes'):
                s.serialize(changed)

    def test_internal_ids_and_child_list_are_validated(self):
        r,_=self.request()
        # The synthetic snapshot has only the General feature, already in XML.
        s.serialize(r)
        r['after_xml']=r['after_xml'].replace(fixtures.VERSION,s.ZERO)
        with self.assertRaisesRegex(ValueError,'internal UUIDs'):s.serialize(r)
        r,_=self.request()
        target=E.fromstring(r['after_xml'])
        E.SubElement(E.SubElement(target[0],'ChildObjects'),'Bogus').text='Missing'
        # Missing child metadata is rejected instead of silently discarding a list.
        with self.assertRaises((ValueError,KeyError)):s.serialize(dict(r,after_xml=E.tostring(target,encoding='unicode')))


if __name__=='__main__':unittest.main()
