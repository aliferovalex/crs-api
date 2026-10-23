"""Recursive controls, command identities, events and complete module replacement."""
import base64, sys, unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import native_metadata as s, managed_form_xml as x, managed_form_elements as e
import managed_form_operations,managed_form_operations,external_data
import test_catalog_form_serializer as creation
import test_managed_form_operations as change
from test_managed_form_xml import xml,extra


def extended():
    root=E.fromstring(xml());items=root.find(x.Q+'ChildItems');fields=list(items);items[:]=[]
    group=E.SubElement(items,x.Q+'UsualGroup',name='Group',id='30');E.SubElement(group,x.Q+'Group').text='Horizontal'
    nested=E.SubElement(group,x.Q+'ChildItems');nested.extend(fields)
    field=fields[0];E.SubElement(field,x.Q+'ReadOnly').text='true';E.SubElement(field,x.Q+'Visible').text='false'
    events=E.SubElement(field,x.Q+'Events');E.SubElement(events,x.Q+'Event',name='OnChange').text='FieldOnChange'
    title=E.SubElement(group,x.Q+'Title');item=E.SubElement(title,'{'+x.CORE+'}item')
    E.SubElement(item,'{'+x.CORE+'}lang').text='ru';E.SubElement(item,'{'+x.CORE+'}content').text='Группа'
    E.SubElement(group,x.Q+'Enabled').text='false'
    button=E.SubElement(nested,x.Q+'Button',name='Button',id='40');E.SubElement(button,x.Q+'Type').text='UsualButton'
    E.SubElement(button,x.Q+'CommandName').text='Form.Command.TestCommand'
    commands=E.SubElement(root,x.Q+'Commands');command=E.SubElement(commands,x.Q+'Command',name='TestCommand',id='7')
    E.SubElement(command,x.Q+'Action').text='TestAction'
    events=E.SubElement(root,x.Q+'Events');E.SubElement(events,x.Q+'Event',name='OnOpen').text='FormOnOpen'
    return root


class ExtendedFormTests(unittest.TestCase):
    def native(self,root=None):
        r=creation.fixture();r['form_xml']=E.tostring(root if root is not None else extended(),encoding='unicode')
        return extra(managed_form_operations.create(r))

    def test_recursive_tree_properties_command_and_events(self):
        form=x.interface(self.native());index,_,_=e.form_collection(form);group=form[1][index+2]
        self.assertEqual(s.val(group[21]),'3');self.assertEqual(s.val(group[20][1]),'1')
        self.assertEqual(s.val(group[10]),'0');self.assertEqual(s.val(group[28]),'1');self.assertEqual(s.val(group[7][2][1]),'Группа')
        self.assertEqual(s.val(group[23][14]),'1');self.assertEqual(s.val(group[23][43]),'0')
        self.assertIn('FieldOnChange',s.render(group[23][40]));self.assertIn('FormOnOpen',s.render(form[1][index-4]))
        command=form[5][2];self.assertEqual(s.val(command[1][0]),'7')
        self.assertEqual(s.render(group[27][8]),s.render(command[1]))
        self.assertEqual(s.val(command[8]),'TestAction')

    def test_moving_children_and_removing_commands_events(self):
        native=self.native();root=extended();items=root.find(x.Q+'ChildItems');group=items[0];nested=group.find(x.Q+'ChildItems')
        items[:]=[nested[1],nested[0]];items[1].remove(items[1].find(x.Q+'Events'))
        root.remove(root.find(x.Q+'Commands'));root.remove(root.find(x.Q+'Events'))
        paths={name:s.Parser(value).documents()[0] for name,value in [('Object.Code','{2,{1},{-2}}'),('Object.Description','{2,{1},{-3}}')]}
        result=x.convert(native,E.tostring(root,encoding='unicode'),paths=paths,object_name='XML_Catalog')
        form=x.interface(result);index,count,end=e.form_collection(form)
        self.assertEqual(count,2);self.assertEqual(s.render(form[5]),'{0,0}')
        self.assertEqual(s.render(form[1][index-4]),'{0,1,0}')
        self.assertEqual(s.render(form[1][end-1][40]),'{0,1,0}')

    def test_rejects_ambiguous_tree_unknown_event_and_broken_command(self):
        for mutation in ('duplicate','event','command','orientation','boolean'):
            root=extended();group=root.find(x.Q+'ChildItems')[0];nested=group.find(x.Q+'ChildItems')
            if mutation=='duplicate':group.set('id','1')
            elif mutation=='event':nested[0].find(x.Q+'Events')[0].set('name','UnknownEvent')
            elif mutation=='command':nested[2].find(x.Q+'CommandName').text='Form.Command.Missing'
            elif mutation=='orientation':group.find(x.Q+'Group').text='Pages'
            else:E.SubElement(nested[0],x.Q+'Enabled').text='perhaps'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.native(root)

    def test_module_only_keeps_interface_and_metadata(self):
        r=change.fixture()
        previous=external_data.extract(base64.b64decode(r['storage']),r['object_id'])
        source=s.inflate(base64.b64decode(previous['externals'][0]['data']));old=x.interface(source)
        for text in ('\ufeff&AtClient\nProcedure Тест()\n    Message("Кириллица");\nEndProcedure',''):
            result=managed_form_operations.change(dict(r,module_text=text));new=x.interface(extra(result))
            self.assertEqual(s.render(old[:2]+old[3:]),s.render(new[:2]+new[3:]))
            self.assertEqual(s.val(new[2]),text.removeprefix('\ufeff').replace('\n','\r\n'))
        with self.assertRaises(ValueError):managed_form_operations.change(dict(r,module_text='bad\0code'))
        with self.assertRaises(ValueError):managed_form_operations.change(dict(r,module_text=None))


if __name__=='__main__':unittest.main()
