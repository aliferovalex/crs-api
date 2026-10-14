"""Accounting profiles share scalar fields, references and recorder changes."""
import copy,unittest
from xml.etree import ElementTree as E
import test_object_xml_profiles as fixture
import test_related_object_changes as recorder
import flat_object_serializer as flat,constant_serializer as c,metadata_serializer as s,related_object_changes as related,type_description_xml as types

Q='{'+c.MD+'}';CHART='77777777-7777-4777-8777-777777777779'

def accounting():
    r=fixture.request('AccountingRegister');objects=c.context_objects(r['context']);d=copy.deepcopy(next(iter(objects.values())))
    d[0][1]=s.atom(CHART);d[0][2]=s.atom(c.identifiers.class_id('ChartOfAccounts'));d[0][9]=s.atom('Accounts',True);objects[CHART]=d
    root=E.fromstring(fixture.xml('AccountingRegister'));E.SubElement(root[0][0],Q+'ChartOfAccounts').text='ChartOfAccounts.Accounts'
    node=E.SubElement(root[0].find(Q+'ChildObjects'),Q+'Resource',uuid=recorder.OLD);props=E.SubElement(node,Q+'Properties');E.SubElement(props,Q+'Name').text='Amount'
    props.append(types.export(s.Parser('{"Pattern",{"N",15,2,0}}').documents()[0],Q+'Type'))
    return root,objects

class AccountingProfileTests(unittest.TestCase):
    def test_chart_of_accounts_identity_types_and_module_streams(self):
        oid,name,body,ids=flat.object_xml(fixture.xml('ChartOfAccounts'),'8.5.1.1529','ChartOfAccounts')
        self.assertEqual(len(ids),14);native=s.Parser(body.decode('utf-8-sig')).documents()[0]
        self.assertEqual(s.val(native[1][15][1][1][2]),fixture.OID)
        r=fixture.request('ChartOfAccounts');r['modules']={'ObjectModule':'// accounts','ManagerModule':'// manager'};result=c.serialize(r)
        self.assertEqual({row['name'] for row in result['externals']},{fixture.OID+'.14',fixture.OID+'.15'})

    def test_accounting_reference_and_numeric_resource(self):
        root,objects=accounting();raw=flat.object_xml(E.tostring(root,encoding='unicode'),'8.5.1.1529','AccountingRegister',objects)[2]
        native=s.Parser(raw.decode('utf-8-sig')).documents()[0];self.assertEqual(s.val(native[1][18]),CHART);self.assertEqual(s.val(native[5][1]),'1')
        with self.assertRaisesRegex(ValueError,'Missing'):flat.object_xml(E.tostring(root,encoding='unicode'),'8.5.1.1529','AccountingRegister',{})
        node=root[0][0].find(Q+'ChartOfAccounts');node.text='ChartOfAccounts.Unknown'
        with self.assertRaisesRegex(ValueError,'Missing'):flat.object_xml(E.tostring(root,encoding='unicode'),'8.5.1.1529','AccountingRegister',objects)
        root,objects=accounting();props=root[0].find(Q+'ChildObjects')[0][0];props.remove(props.find(Q+'Type'));props.append(types.export(s.Parser('{"Pattern",{"B"}}').documents()[0],Q+'Type'))
        with self.assertRaisesRegex(ValueError,'scalar type'):flat.object_xml(E.tostring(root,encoding='unicode'),'8.5.1.1529','AccountingRegister',objects)

    def test_accounting_reuses_whole_recorder_update(self):
        r,objects,raws,versions=recorder.input();objects[recorder.REG][0][2]=s.atom(c.identifiers.class_id('AccountingRegister'))
        r['related_objects'][0]['object_xml']=r['related_objects'][0]['object_xml'].replace('AccumulationRegister.NewRegister','AccountingRegister.NewRegister')
        self.assertEqual(related.apply(r,objects,raws,versions,recorder.REG,'AccountingRegister'),[recorder.DOC])
        self.assertEqual(s.metadata_relations(objects[recorder.DOC][0][14])[recorder.REG],0)

    def test_unsupported_chart_subconto_and_accounting_correspondence_reject(self):
        for kind,key,value in [('ChartOfAccounts','MaxExtDimensionCount','3'),('AccountingRegister','Correspondence','true')]:
            root=E.fromstring(fixture.xml(kind));E.SubElement(root[0][0],Q+key).text=value
            with self.subTest(kind=kind),self.assertRaises(ValueError):flat.object_xml(E.tostring(root,encoding='unicode'),'8.5.1.1529',kind)

if __name__=='__main__':unittest.main()
