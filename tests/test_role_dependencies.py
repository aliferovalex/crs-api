"""Textually unchanged role exports must follow replaced inline UUIDs."""
import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as E
import sys
sys.path.insert(0,str(next(p for p in (Path(__file__).resolve().parents[1]/'src').iterdir() if (p/'role_dependencies.py').exists())))
import role_dependencies as roles
import native_metadata as s
import metadata_identifiers as ids
from test_metadata_definitions import fixture,oid


class RoleDependencyTests(unittest.TestCase):
    def test_replaced_field_adds_unchanged_role_once(self):
        old=fixture();target=copy.deepcopy(old);node=next(n for n in target[oid(2)]['node'].iter() if n.get('uuid')==oid(13));node.set('uuid',oid(30))
        role=oid(40);md=[s.atom(0)]*17;md[2]=s.atom(ids.class_id('Role'));md[14]=[s.atom(1),s.atom(oid(13)),s.atom(1)]
        target[role]=dict(kind='Role',path='Roles/Test.xml',node=E.Element('Role',uuid=role));objects={role:[md]}
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'Roles/Test/Ext/Rights.xml';file.parent.mkdir(parents=True);file.write_text('unchanged')
            plan=dict(operations=[dict(operation='Изменение',object_id=oid(2),xml_path=str(Path(temp)/'Catalogs/Items.xml'),changed_files=['Catalogs/Items.xml'])],xml_paths=[str(Path(temp)/'Catalogs/Items.xml')],removed_ids=[],unchanged_count=1)
            target[oid(2)]['path']='Catalogs/Items.xml'
            with patch.object(roles.configuration_export,'inventory',return_value=(None,None,old,None)):
                self.assertEqual(roles.expand(plan,target,objects,temp,'baseline'),[role])
                self.assertEqual(roles.expand(plan,target,objects,temp,'baseline'),[])
            self.assertEqual(plan['unchanged_count'],0);self.assertEqual(plan['operations'][-1]['changed_files'],[])
            self.assertEqual(file.read_text(),'unchanged')

    def test_unrelated_uuid_changes_and_companions_do_not_schedule_roles(self):
        old=fixture();target=copy.deepcopy(old);target[oid(2)]['path']='Catalogs/Items.xml'
        node=next(n for n in target[oid(2)]['node'].iter() if n.get('uuid')==oid(12));node.set('uuid',oid(31))
        role=oid(40);md=[s.atom(0)]*17;md[2]=s.atom(ids.class_id('Role'));md[14]=[s.atom(1),s.atom(oid(13)),s.atom(1)]
        target[role]=dict(kind='Role',path='Roles/Test.xml',node=E.Element('Role',uuid=role))
        plan=dict(operations=[dict(operation='Изменение',object_id=oid(2),xml_path='Catalogs/Items.xml',changed_files=['Catalogs/Items.xml'])],xml_paths=['Catalogs/Items.xml'],removed_ids=[],unchanged_count=1)
        with patch.object(roles.configuration_export,'inventory',return_value=(None,None,old,None)):
            self.assertEqual(roles.expand(plan,target,{role:[md]},'.','baseline'),[])
        plan['operations'][0]['changed_files']=['Catalogs/Items/Ext/ObjectModule.bsl']
        with patch.object(roles.configuration_export,'inventory') as read:
            self.assertEqual(roles.expand(plan,target,{role:[md]},'.','baseline'),[])
            read.assert_not_called()


if __name__=='__main__':unittest.main()
