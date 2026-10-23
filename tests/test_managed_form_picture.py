"""Standard references, decoration variants and complete picture replacement."""
import sys, unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/Сериализация'))
import native_metadata as s, managed_form_xml as x, managed_form_operations as creation
import picture_xml as picture,v8unpack_backend as backend
import test_catalog_form_serializer as fixture
from test_managed_form_xml import xml,extra


def root(name='Refresh',transparent='true'):
    result=E.fromstring(xml());items=result.find(x.Q+'ChildItems');items.clear()
    node=E.SubElement(items,x.Q+'PictureDecoration',name='Logo',id='170')
    if name is not None:
        ref=E.SubElement(node,x.Q+'Picture');E.SubElement(ref,picture.XR+'Ref').text='StdPicture.'+name
        E.SubElement(ref,picture.XR+'LoadTransparent').text=transparent
    return result


def native(value):
    request=fixture.fixture();request['form_xml']=E.tostring(value,encoding='unicode')
    return extra(creation.create(request))


def change(raw,value):
    return x.convert(raw,E.tostring(value,encoding='unicode'),paths={},object_name='XML_Catalog')


def entry(raw):return backend.form_model(x.interface(raw))['elements']['data']['Logo']['raw']


class PictureTests(unittest.TestCase):
    def test_guid_and_numeric_standard_references(self):
        for name in ['Refresh','Print','CreateListItem','DeleteListItem','Write','Information']:
            raw=native(root(name));value=entry(raw)
            self.assertEqual(value[5],'1');self.assertEqual(value[18][1][1],'1')
            expected=s.Parser(picture.profile()['references'][name]).documents()[0]
            self.assertEqual(value[18][1][2],backend.to_model(expected))
        self.assertEqual(entry(native(root('Print')))[18][1][2],['-13'])

    def test_replacement_transparency_and_clear_use_whole_xml(self):
        raw=native(root());changed=change(raw,root('Print','false'));value=entry(changed)
        self.assertEqual(value[18][1][2],['-13']);self.assertEqual(value[18][1][6],'0')
        empty=change(changed,root(None));self.assertEqual(entry(empty)[18][1][1],'0')
        deleted=root(None);deleted.find(x.Q+'ChildItems').clear()
        self.assertFalse(backend.form_model(x.interface(change(empty,deleted)))['elements']['tree'])

    def test_flags_and_picture_settings_are_independent(self):
        value=root();node=value.find(x.Q+'ChildItems')[0]
        for prop in ['Enabled','Visible']:E.SubElement(node,x.Q+prop).text='false'
        for prop in ['Zoomable','Hyperlink']:E.SubElement(node,x.Q+prop).text='true'
        values=entry(native(value));self.assertEqual(values[9],'0');self.assertEqual(values[21],'0')
        self.assertEqual(values[18][4],'1');self.assertEqual(values[18][2],'1')

    def test_unverified_common_absolute_and_incomplete_references_are_rejected(self):
        variants=[]
        for ref in ['StdPicture.Missing','CommonPicture.Logo','style:Picture']:
            value=root();value.find('.//'+picture.XR+'Ref').text=ref;variants.append(value)
        absolute=root();ref=absolute.find('.//'+x.Q+'Picture');ref[0].tag=picture.XR+'Abs';ref[0].text='logo.png';variants.append(absolute)
        missing=root();ref=missing.find('.//'+x.Q+'Picture');ref.remove(ref.find(picture.XR+'LoadTransparent'));variants.append(missing)
        invalid=root(transparent='sometimes');variants.append(invalid)
        for value in variants:
            with self.assertRaises(ValueError):native(value)


if __name__=='__main__':unittest.main()
