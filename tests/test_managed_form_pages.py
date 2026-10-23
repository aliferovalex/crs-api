"""Native group variants, plain labels and complete page tree replacement."""
import copy,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/Сериализация'))
import native_metadata as s, managed_form_xml as x, managed_form_elements as e
import managed_form_operations as creation,v8unpack_backend as backend
import test_catalog_form_serializer as fixture
from test_managed_form_xml import xml,extra


def caption(node,value,formatted=False):
    title=E.SubElement(node,x.Q+'Title',{'formatted':'false'} if formatted else {})
    item=E.SubElement(title,'{'+x.CORE+'}item');E.SubElement(item,'{'+x.CORE+'}lang').text='ru';E.SubElement(item,'{'+x.CORE+'}content').text=value


def pages():
    root=E.fromstring(xml());items=root.find(x.Q+'ChildItems');old=list(items);items.clear()
    tabs=E.SubElement(items,x.Q+'Pages',name='Tabs',id='100');children=E.SubElement(tabs,x.Q+'ChildItems')
    page=E.SubElement(children,x.Q+'Page',name='MainPage',id='110');caption(page,'Main');nested=E.SubElement(page,x.Q+'ChildItems')
    label=E.SubElement(nested,x.Q+'LabelDecoration',name='Heading',id='120');caption(label,'Page heading',True)
    E.SubElement(label,x.Q+'Enabled').text='false';nested.extend(old)
    second=E.SubElement(children,x.Q+'Page',name='ExtraPage',id='130');caption(second,'Extra');E.SubElement(second,x.Q+'ChildItems')
    return root


def native(root):
    request=fixture.fixture();request['form_xml']=E.tostring(root,encoding='unicode')
    return extra(creation.create(request))


def change(raw,root):
    paths={name:s.Parser(value).documents()[0] for name,value in [('Object.Code','{2,{1},{-2}}'),('Object.Description','{2,{1},{-3}}')]}
    return x.convert(raw,E.tostring(root,encoding='unicode'),paths=paths,object_name='XML_Catalog')


class PageTests(unittest.TestCase):
    def test_upstream_tree_and_native_group_variants(self):
        raw=native(pages());model=backend.form_model(x.interface(raw));tree=model['elements']['tree']
        self.assertEqual(tree[0]['type'],'Group');self.assertEqual([p['name'] for p in tree[0]['child']],['MainPage','ExtraPage'])
        label=model['elements']['data']['Tabs/MainPage/Heading']['raw']
        self.assertEqual(label[9],'0');self.assertEqual(label[21],'1')
        form=x.interface(raw);index,_,_=e.form_collection(form);tabs=form[1][index+2];first=tabs[23]
        self.assertEqual(s.val(tabs[5]),'3');self.assertEqual(s.val(first[5]),'4')
        decoration=first[23];self.assertEqual(s.render(decoration[7]),s.render(decoration[23][1]))

    def test_full_tree_moves_labels_reorders_pages_and_removes_children(self):
        root=pages();raw=native(root);tabs=root.find(x.Q+'ChildItems')[0];children=tabs.find(x.Q+'ChildItems')
        label=children[0].find(x.Q+'ChildItems')[0];children[0].find(x.Q+'ChildItems').remove(label)
        children[1].find(x.Q+'ChildItems').append(label);children[:]=list(reversed(children))
        changed=change(raw,root);model=backend.form_model(x.interface(changed));tree=model['elements']['tree'][0]['child']
        self.assertEqual([p['name'] for p in tree],['ExtraPage','MainPage']);self.assertEqual(tree[0]['child'][0]['name'],'Heading')
        children.clear();empty=change(changed,root)
        self.assertFalse(backend.form_model(x.interface(empty))['elements']['tree'][0].get('child'))

    def test_group_enabled_and_visible_are_independent(self):
        root=E.fromstring(xml());items=root.find(x.Q+'ChildItems');items.clear()
        group=E.SubElement(items,x.Q+'UsualGroup',name='PlainGroup',id='160');E.SubElement(group,x.Q+'Enabled').text='false'
        raw=native(root);model=backend.form_model(x.interface(raw));values=model['elements']['data']['PlainGroup']['raw']
        self.assertEqual(values[10],'0');self.assertEqual(values[22],'1')
        group.remove(group.find(x.Q+'Enabled'));E.SubElement(group,x.Q+'Visible').text='false'
        values=backend.form_model(x.interface(change(raw,root)))['elements']['data']['PlainGroup']['raw']
        self.assertEqual(values[10],'1');self.assertEqual(values[22],'0')

    def test_page_hierarchy_invalid_formatted_title_and_duplicate_ids_are_rejected(self):
        root=pages();bad=copy.deepcopy(root);items=bad.find(x.Q+'ChildItems');page=items[0].find(x.Q+'ChildItems')[0];items.append(page)
        wrong=copy.deepcopy(root);nested=wrong.find(x.Q+'ChildItems')[0].find(x.Q+'ChildItems');E.SubElement(nested,x.Q+'LabelDecoration',name='Outside',id='150')
        formatted=copy.deepcopy(root);formatted.find('.//'+x.Q+'LabelDecoration/'+x.Q+'Title').set('formatted','invalid')
        duplicate=copy.deepcopy(root);duplicate.find('.//'+x.Q+'LabelDecoration').set('id','110')
        for value in [bad,wrong,formatted,duplicate]:
            with self.assertRaises(ValueError):native(value)


if __name__=='__main__':unittest.main()
