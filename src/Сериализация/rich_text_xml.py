"""Whole formatted titles: raw markup and the native plain text projection."""
import copy
import native_metadata as s


def plain_text(text):
    result=[];index=0
    while index<len(text):
        if text[index]!='<':result.append(text[index]);index+=1;continue
        if text[index:index+2]=='<<':result.append('<');index+=2;continue
        end=text.find('>',index+1)
        if end<0:break
        tag=text[index+1:end]
        if tag=='img' or tag.startswith('img '):result.append(' ')
        index=end+1
    return ''.join(result)


def title_values(node):
    from managed_form_elements import title
    formatted='false' if node is None else node.get('formatted','false')
    if formatted not in ('true','false') or (node is not None and set(node.attrib)-{'formatted'}):raise ValueError('Unsupported formatted Title attributes')
    clean=copy.deepcopy(node) if node is not None else None
    if clean is not None:clean.attrib.clear()
    original=title(clean);plain=copy.deepcopy(original)
    if formatted=='true':
        entries=[]
        for lang,content in original[2:]:
            text=plain_text(s.val(content))
            if text:entries.append([copy.deepcopy(lang),s.atom(text,True)])
        plain=[s.atom(1),s.atom(len(entries))]+entries
    return plain,[s.atom(1),original,s.atom(1 if formatted=='true' else 0)]
