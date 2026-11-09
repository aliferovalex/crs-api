"""Sparse view contexts use body ownership and historical names, not full bodies."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import native_metadata as s
import metadata_identifiers as ids
import object_view_context as c
import xml_namespaces

ROOT='11111111-1111-4111-8111-111111111111'
A='22222222-2222-4222-8222-222222222222'
B='33333333-3333-4333-8333-333333333333'
Q='{http://v8.1c.ru/8.3/MDClasses}'


class ViewContextTests(unittest.TestCase):
    def test_root_reference_is_retained_outside_ownership_collection(self):
        language=ids.class_id('Language')
        body=s.text_bytes([[s.atom(0), [s.atom(language), s.atom(2), s.atom(A), s.atom(B)], s.atom(A), s.atom(B,True)]])
        with patch.object(c.native_configuration_reader, 'stored_collections', return_value={language:[A,B]}):
            result=c.plan(body,ROOT,'Configuration','8.5.1.1529')
        self.assertEqual(result['references'],[A])
        self.assertEqual(result['collections'],[dict(class_id=language,tag='Language',ids=[A,B])])

    def test_catalog_children_are_read_from_body_even_without_service_map(self):
        form=ids.class_id('CatalogForm')
        body=s.text_bytes([[s.atom(0),[s.atom(form),s.atom(2),s.atom(A),s.atom(B)]]])
        result=c.plan(body,ROOT,'Catalog','8.5.1.1529')
        self.assertEqual(result['collections'],[dict(class_id=form,tag='Form',ids=[A,B])])
        self.assertEqual(result['references'],[])
        bad=body.replace(b',2,',b',3,',1)
        with self.assertRaises(ValueError):c.plan(bad,ROOT,'Catalog','8.5.1.1529')

    def source(self):
        return ('<MetaDataObject xmlns="'+Q[1:-1]+'" xmlns:cfg="urn:cfg"><Configuration uuid="'+ROOT+'">'
                '<Properties><Name>Test</Name><Type>cfg:CatalogRef.Target</Type></Properties>'
                '<ChildObjects><Language>Russian</Language></ChildObjects></Configuration></MetaDataObject>').encode()

    def descriptions(self):
        return {A:dict(class_id=ids.class_id('Language'),parent_id=ROOT,name='Russian'),
                B:dict(class_id=ids.class_id('Catalog'),parent_id=ROOT,name='Target')}

    def groups(self):
        return [dict(class_id=ids.class_id('Language'),tag='Language',ids=[A]),
                dict(class_id=ids.class_id('Catalog'),tag='Catalog',ids=[B])]

    def test_historical_names_complete_xml_without_other_object_bodies(self):
        raw=c.bind_children(self.source(),ROOT,self.groups(),self.descriptions())
        root=E.fromstring(raw);children=root[0].find(Q+'ChildObjects')
        self.assertEqual([(n.tag,n.text) for n in children],[(Q+'Language','Russian'),(Q+'Catalog','Target')])
        self.assertEqual(E.tostring(root[0].find(Q+'Properties')),E.tostring(E.fromstring(self.source())[0].find(Q+'Properties')))
        self.assertEqual(xml_namespaces.namespace_bindings(raw.decode())['cfg'],'urn:cfg')
        self.assertEqual(root[0].findtext(Q+'Properties/'+Q+'Type'),'cfg:CatalogRef.Target')

    def test_missing_foreign_or_conflicting_names_do_not_become_empty_diff(self):
        for change in ('missing','class','parent','duplicate'):
            desc=self.descriptions();groups=self.groups()
            if change=='missing':desc.pop(B)
            elif change=='class':desc[B]['class_id']=ids.class_id('Document')
            elif change=='parent':desc[B]['parent_id']=A
            else:groups[1]['ids']=[B,B]
            with self.subTest(change=change),self.assertRaises(ValueError):c.bind_children(self.source(),ROOT,groups,desc)
        with self.assertRaises(ValueError):c.bind_children(self.source().replace(b'Russian',b'Wrong'),ROOT,self.groups(),self.descriptions())

    def test_snapshot_versions_determine_names_not_current_state(self):
        old=self.descriptions();new=self.descriptions();new[B]['name']='Renamed'
        a=E.fromstring(c.bind_children(self.source(),ROOT,self.groups(),old))
        b=E.fromstring(c.bind_children(self.source(),ROOT,self.groups(),new))
        self.assertEqual(a[0].findtext(Q+'ChildObjects/'+Q+'Catalog'),'Target')
        self.assertEqual(b[0].findtext(Q+'ChildObjects/'+Q+'Catalog'),'Renamed')
