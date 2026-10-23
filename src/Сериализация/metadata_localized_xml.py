"""Localized metadata properties share a counted sequence of language/text pairs."""
import re
import native_metadata as s
from xml.etree import ElementTree as E

CORE='{http://v8.1c.ru/8.1/data/core}'


def read(node,label='Localized property'):
    result=[s.atom(0)];languages=set()
    if node is None:return result
    if node.attrib or (node.text or '').strip():raise ValueError('Unsupported '+label+' structure')
    for item in node:
        if (item.tag!=CORE+'item' or item.attrib or [child.tag for child in item]!=[CORE+'lang',CORE+'content']
                or any(child.attrib or len(child) for child in item) or (item.text or '').strip()
                or (item.tail or '').strip() or (item[0].tail or '').strip() or (item[1].tail or '').strip()):
            raise ValueError('Unsupported '+label+' structure')
        lang=item[0].text or ''
        if not re.fullmatch('[a-zA-Z][a-zA-Z0-9_-]*',lang) or lang in languages:
            raise ValueError('Invalid or duplicate '+label+' language')
        languages.add(lang);result.extend([s.atom(lang,True),s.atom(item[1].text or '',True)])
    result[0]=s.atom(len(languages));return result


def write(node,values,label='Localized property'):
    """Restore all languages, rejecting unrepresentable native collections."""
    if not isinstance(values,list) or not values:raise ValueError('Invalid native '+label)
    try:count=int(s.val(values[0]))
    except (TypeError,ValueError):raise ValueError('Invalid native '+label+' count') from None
    if count<0 or len(values)!=1+2*count:raise ValueError('Invalid native '+label+' count')
    for index in range(1,len(values),2):
        item=E.SubElement(node,CORE+'item');E.SubElement(item,CORE+'lang').text=s.val(values[index]);E.SubElement(item,CORE+'content').text=s.val(values[index+1])
    if s.render(read(node,label))!=s.render(values):raise ValueError('Unsupported native '+label)
    return node
