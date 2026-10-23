"""Root XML uses the current native snapshot instead of a prior XML export."""
import base64, hashlib, json, sys, unittest
import copy
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import configuration_serializer
import configuration_xml
import metadata_context
import metadata_identifiers
import native_metadata as s
import test_configuration_serializer as fixtures


class WithoutBaselineTests(unittest.TestCase):
    def test_runtime_child_class_aliases_use_configurator_xml_names(self):
        aliases=[('ChartOfCharacteristicType','ChartOfCharacteristicTypes'),
                 ('DocumentNumerators','DocumentNumerator'),('Sequences','Sequence')]
        for runtime,xml_name in aliases:
            r,raw=self.request();docs=metadata_context.context_metadata(base64.b64decode(r['context']),fixtures.ID)
            child=copy.deepcopy(docs);cls=metadata_identifiers.class_id(runtime)
            docs[0][12]=[s.atom(1),[s.atom(cls),s.atom(1),s.atom(fixtures.CHILD)]]
            child[0][1]=s.atom(fixtures.CHILD);child[0][2]=s.atom(cls);child[0][3]=s.atom(fixtures.ID);child[0][9]=s.atom('AliasChild',True)
            child[0][12]=[s.atom(0)];child[0][13]=[s.atom(0)]
            context=base64.b64encode(s.storage([s.text_bytes(docs),s.text_bytes(child)],s.text_bytes([[s.atom(0)]]))).decode()
            root=E.fromstring(r['after_xml']);q='{http://v8.1c.ru/8.3/MDClasses}'
            E.SubElement(E.SubElement(root[0],q+'ChildObjects'),q+xml_name).text='AliasChild'
            native=s.Parser(raw.decode('utf-8-sig')).documents();common=configuration_xml.common_properties(native,fixtures.ID,r['platform'])
            with self.subTest(runtime=runtime):
                configuration_xml.configuration_baseline_from_snapshot(E.tostring(root,encoding='unicode'),fixtures.ID,common,native,r['platform'],context)

    def request(self):
        r,raw=fixtures.property_fixture('8.5.1.1529')
        r.pop('before_xml')
        r['after_xml']=r['after_xml'].replace('<Comment>До</Comment>','<Comment>Target</Comment>')
        return r,raw

    def test_same_body_with_and_without_prior_xml(self):
        r,raw=self.request()
        _,actual=configuration_serializer.serialize(r)
        r['before_xml']=fixtures.property_fixture('8.5.1.1529')[0]['before_xml']
        _,expected=configuration_serializer.serialize(r)
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
            with self.subTest(xml=xml),self.assertRaises(ValueError):configuration_serializer.serialize(dict(r,after_xml=xml))

    def test_verified_unmapped_property_and_native_guard(self):
        r,raw=self.request();docs=s.Parser(raw.decode('utf-8-sig')).documents()
        props=configuration_xml.configuration_properties(docs,'8.5.1.1529')
        profile=json.loads(Path(s.__file__).with_name('configuration_profile_851.json').read_text(encoding='utf-8'))
        for i,value in profile['native_slots'].items():props[int(i)]=s.Parser(value).documents()[0]
        def snapshot():
            meta,_=s.read_record(base64.b64decode(r['snapshot']),12)
            data=s.compress(s.text_bytes(docs))
            manifest=s.text_bytes([[s.atom(0),s.atom(1),s.atom(fixtures.ID),s.atom(hashlib.sha1(meta).hexdigest(),True),s.atom(hashlib.sha1(data).hexdigest(),True),s.atom(0)]])
            r['snapshot']=base64.b64encode(s.storage([meta,data],manifest)).decode()
        target=E.fromstring(r['after_xml']);target[0].remove(target[0].find('InternalInfo'));p=target.find('.//Properties')
        E.SubElement(p,'{http://v8.1c.ru/8.3/MDClasses}DefaultRunMode').text='ManagedApplication'
        r['after_xml']=E.tostring(target,encoding='unicode');snapshot();configuration_serializer.serialize(r)
        props[3]=s.atom(0);snapshot()
        with self.assertRaisesRegex(ValueError,'native profile'):configuration_serializer.serialize(r)
        props[3]=s.atom(1);snapshot();p[-1].text='OrdinaryApplication'
        with self.assertRaisesRegex(ValueError,'DefaultRunMode'):configuration_serializer.serialize(dict(r,after_xml=E.tostring(target,encoding='unicode')))

    def test_no_changes(self):
        r,_=self.request();r['after_xml']=r['after_xml'].replace('Target','До')
        with self.assertRaisesRegex(ValueError,'have not changed'):configuration_serializer.serialize(r)

    def test_comment_uses_common_converter_with_or_without_baseline(self):
        r,_=self.request()
        _,properties=configuration_serializer.serialize(r)
        r['mode']='comment'
        _,comment=configuration_serializer.serialize(r)
        self.assertEqual(comment,properties)
        r['before_xml']=fixtures.property_fixture('8.5.1.1529')[0]['before_xml']
        _,legacy=configuration_serializer.serialize(r)
        self.assertEqual(legacy,comment)
        # The compatibility wrapper retains its comment-only contract.
        for baseline in (r['before_xml'],None):
            changed=dict(r,before_xml=baseline,after_xml=r['after_xml'].replace('Тест','Another vendor'))
            with self.subTest(baseline=baseline),self.assertRaisesRegex(ValueError,'Unsupported XML changes'):
                configuration_serializer.serialize(changed)

    def test_internal_ids_and_child_list_are_validated(self):
        r,_=self.request()
        # The synthetic snapshot has only the General feature, already in XML.
        configuration_serializer.serialize(r)
        r['after_xml']=r['after_xml'].replace(fixtures.VERSION,s.ZERO)
        with self.assertRaisesRegex(ValueError,'internal UUIDs'):configuration_serializer.serialize(r)
        r,_=self.request()
        target=E.fromstring(r['after_xml'])
        E.SubElement(E.SubElement(target[0],'ChildObjects'),'Bogus').text='Missing'
        # Missing child metadata is rejected instead of silently discarding a list.
        with self.assertRaises((ValueError,KeyError)):configuration_serializer.serialize(dict(r,after_xml=E.tostring(target,encoding='unicode')))


if __name__=='__main__':unittest.main()
