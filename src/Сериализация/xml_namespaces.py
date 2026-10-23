"""Retain prefixes used inside QName values when rewriting an XML tree."""
from xml.etree import ElementTree as E
from xml.sax.saxutils import quoteattr
from io import StringIO
import copy,re


class NamespaceScopes(dict):
    def __init__(self):
        super().__init__();self.declarations={}


def parse(text):
    """Keep namespace bindings at each element, including locally rebound prefixes."""
    scopes=NamespaceScopes();pending={};stack=[];current={};root=None
    for event,value in E.iterparse(StringIO(text),events=('start-ns','start','end')):
        if event=='start-ns':pending[value[0]]=value[1]
        elif event=='start':
            stack.append(current);current=dict(current);current.update(pending);scopes.declarations[value]=dict(pending);pending={};scopes[value]=current
            if root is None:root=value
        else:current=stack.pop()
    return root,scopes


def context(bindings,node):
    return (bindings or {}).get(node,bindings or {})


def namespace_bindings(text,label='XML'):
    result={}
    for _,(prefix,uri) in E.iterparse(StringIO(text),events=('start-ns',)):
        if prefix in result and result[prefix]!=uri:raise ValueError('Ambiguous '+label+' namespace prefix')
        result[prefix]=uri
    return result


def serialize(root):
    """Keep literal CR text distinct from line breaks normalized by XML readers."""
    return E.tostring(root,encoding='unicode').replace('\r','&#13;')


def render(root,original,scopes=None):
    if scopes is not None:
        result=copy.deepcopy(root);inherited={root:{}}
        for source,target in zip(root.iter(),result.iter()):
            parent=inherited[source]
            if isinstance(scopes,NamespaceScopes):bindings=dict(parent);bindings.update(scopes.declarations.get(source,{}))
            else:bindings=dict(scopes.get(source,parent))
            for key,value in source.attrib.items():
                if key=='xmlns':bindings['']=value
                elif key.startswith('xmlns:'):bindings[key[6:]]=value
            default=bindings.get('','')
            if default!=parent.get('',''):target.set('xmlns',default)
            for child in source:inherited[child]=bindings
            for value in [source.text or '']+list(source.attrib.values()):
                match=re.fullmatch(r'([^\W\d][\w.-]*):[^\W\d][\w.-]*',value.strip())
                if match and match[1] in bindings:target.set('xmlns:'+match[1],bindings[match[1]])
        return serialize(result)
    text=serialize(root)
    declarations=[]
    for prefix,uri in namespace_bindings(original).items():
        if not prefix and 'xmlns=' not in text[:text.index('>')]:
            declarations.append(' xmlns='+quoteattr(uri))
        elif prefix and prefix!='xml' and 'xmlns:'+prefix+'=' not in text:
            declarations.append(' xmlns:'+prefix+'='+quoteattr(uri))
    if declarations:
        end=text.index('>')
        if text[end-1]=='/':end-=1
        text=text[:end]+''.join(declarations)+text[end:]
    return text


MD = 'http://v8.1c.ru/8.3/MDClasses'
CORE = 'http://v8.1c.ru/8.1/data/core'
READABLE = 'http://v8.1c.ru/8.3/xcf/readable'
