"""Document reuses inline scalar and tabular converters for whole XML."""
import json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
import metadata_serializer as s
import flat_object_serializer as flat
import inline_object_xml as inline
import object_change_serializer as change
import catalog_tabular_xml as tabular
import test_catalog_tabular_xml as tables
import test_document_serializer as document
import test_object_change_serializer as snapshots


def xml():
    root=E.fromstring(document.xml());section=tables.section()
    for node in section.find(tables.c.Q+'InternalInfo'):
        node.set('name',node.get('name').replace('CatalogTabular','DocumentTabular').replace('XML_Catalog','XML_Document'))
    root[0].find(tables.c.Q+'ChildObjects').append(section)
    return E.tostring(root,encoding='unicode')


class DocumentInlineTests(unittest.TestCase):
    def test_full_creation_body_and_shared_export(self):
        oid,name,raw,generated=flat.object_xml(xml(),'8.5.1.1529','Document')
        body=s.Parser(raw.decode('utf-8-sig')).documents()[0];layout=json.loads(Path(flat.__file__).with_name('document_layout_851.json').read_text(encoding='utf-8'))
        self.assertEqual(set(inline.features(body,layout)),{tables.SID,tables.AID,tables.BID})
        section=tabular.collection(body,'Document')[0]
        self.assertEqual(s.render(section[0][2]),'9')
        exported=tabular.export(section,name,'Document');_,_,rebuilt,_,_=tabular.read(exported,name,section,'Document')
        self.assertEqual(s.render(rebuilt),s.render(section))

    def test_delete_nested_field_from_whole_xml(self):
        request,_,_=snapshots.fixture('Document',xml());root=E.fromstring(request['object_xml'])
        fields=root.find('.//'+tables.c.Q+'TabularSection/'+tables.c.Q+'ChildObjects');fields.remove(fields[0])
        request['object_xml']=E.tostring(root,encoding='unicode');_,docs,raw,_,_=snapshots.unpack(change.serialize(request))
        self.assertEqual({s.val(n) for n in docs[0][13][1:]},{tables.SID,tables.BID})
        self.assertNotIn(tables.AID,raw.decode('utf-8-sig'))

    def test_document_form_resolves_ordinary_attribute_uuid(self):
        import managed_form_xml as forms
        root=E.fromstring(xml());node=tables.section().find(tables.c.Q+'ChildObjects')[0]
        root[0].find(tables.c.Q+'ChildObjects').remove(root[0].find(tables.c.Q+'ChildObjects')[0])
        root[0].find(tables.c.Q+'ChildObjects').append(node)
        raw=flat.object_xml(E.tostring(root,encoding='unicode'),'8.5.1.1529','Document')[2]
        paths=forms.object_paths(s.Parser(raw.decode('utf-8-sig')).documents()[0],'Document')
        self.assertEqual(s.render(paths['Object.Text']),'{2,{1},{0,'+tables.AID+'}}')

    def test_generated_types_and_owner_scope_are_stable(self):
        for action in ('generated','move'):
            request,_,_=snapshots.fixture('Document',xml());root=E.fromstring(request['object_xml']);section=root.find('.//'+tables.c.Q+'TabularSection')
            if action=='generated':section.find(tables.c.Q+'InternalInfo')[0][0].text='99999999-9999-4999-8999-999999999999'
            else:
                fields=section.find(tables.c.Q+'ChildObjects');field=fields[0];fields.remove(field);root[0].find(tables.c.Q+'ChildObjects').append(field)
            request['object_xml']=E.tostring(root,encoding='unicode')
            with self.subTest(action=action),self.assertRaises(ValueError):change.serialize(request)


if __name__=='__main__':unittest.main()
