"""Legacy version routing and serialization, without a live repository."""
import unittest
import xml.etree.ElementTree as E
import test_constant_serializer as const
import test_catalog_serializer as catalog
import test_comment_serializer as comment
import platform_profiles as p
import comment_serializer as s
import constant_serializer as c
import catalog_serializer as cat

LEGACY=('8.5.1.1529','8.5.1.1150','8.5.1.9999','8.5.0.1','8.3.27.2342','8.3.10.1','8.2.19.1')


class PlatformProfileTests(unittest.TestCase):
    def test_version_routing_and_invalid_versions(self):
        for version in LEGACY:
            with self.subTest(version=version):
                self.assertTrue(p.legacy(version))
                self.assertEqual(p.configuration_layout(version),(76,77))
        self.assertFalse(p.legacy('8.5.4.1878'))
        for version in ('8.5.2.1','8.5.4.2000','9.0.0.1','8.5.1','8.5.1.-1','garbage',None):
            with self.subTest(version=version),self.assertRaises(ValueError):p.profile(version)

    def test_legacy_property_packet_preserves_requested_platform(self):
        for version in LEGACY:
            request,original=comment.property_fixture('8.5.1.1529')
            request['platform']=version
            request['mode']='comment'
            request['after_xml']=request['before_xml'].replace('<Comment>До</Comment>','<Comment>После</Comment>')
            packet,raw=s.serialize(request)
            self.assertEqual(E.fromstring(packet).get('version'),version)
            self.assertEqual(raw,original.replace('"До"'.encode(),'"После"'.encode(),1))

    def test_legacy_creation_body_and_packet(self):
        for version in LEGACY:
            request=const.fixture('8.5.1.1529');request['platform']=version
            result=c.serialize(request)
            self.assertEqual(E.fromstring(result['request_xml']).get('version'),version)
            body=c.constant_xml(const.xml(),version)[2]
            common=s.Parser(body.decode('utf-8-sig')).documents()[0][1][1][1][1]
            self.assertEqual((s.val(common[0]),len(common)),('3',9))
            self.assertEqual(len(cat.catalog_xml(catalog.xml(),version)[3]),10)

    def test_old_xml_revision_and_incompatible_snapshot(self):
        self.assertEqual(len(cat.catalog_xml(catalog.xml().replace('2.21','2.16'),'8.3.10.1')[3]),10)
        for attrs in ({'version':'2.22'},{'version':'2.-1'},{'version':'3.0'},{'unknown':'x'}):
            self.assertFalse(p.xml_attributes(attrs,'8.3.27.2342'))
        request,_=comment.property_fixture('8.5.4.1878');request['platform']='8.3.27.2342'
        with self.assertRaisesRegex(ValueError,'layout'):s.serialize(request)


if __name__=='__main__':unittest.main()
