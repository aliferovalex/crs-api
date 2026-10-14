"""Localized metadata properties share a counted sequence of language/text pairs."""
import re
import metadata_serializer as s

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
