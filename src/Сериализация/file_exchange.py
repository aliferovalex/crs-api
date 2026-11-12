"""Bounded HTTP/TCP receive and streaming CRS base64 extraction to new files."""
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import tempfile
import time
from urllib.parse import urlsplit,quote
import uuid
from xml.parsers import expat

import resource_limits as limits
from native_storage_file import FileStorage,publish_new

CHUNK = 64*1024
NS = 'http://v8.1c.ru/8.2/crs'
END = bytes.fromhex('6653b2a6')


def request_method(path):
    """Read only the opening call tag; never retain authentication or payload."""
    method=None
    class Found(Exception):pass
    parser=expat.ParserCreate(namespace_separator='|')
    def start(name,attrs):
        nonlocal method
        candidate=attrs.get('name','')
        if name==NS+'|call' and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,95}',candidate):method=candidate
        raise Found()
    def forbidden(*args):raise Found()
    parser.StartElementHandler=start
    parser.StartDoctypeDeclHandler=forbidden
    try:
        with Path(path).open('rb') as stream:parser.Parse(stream.read(4096),False)
    except (Found,expat.ExpatError,OSError):pass
    return method


def trace_rpc(row):
    """Opt-in bounded metadata log. Diagnostic failure cannot change a write."""
    target=os.environ.get('CRS_RPC_TRACE')
    if not target:return
    try:
        path=Path(target)
        if path.exists() and (path.is_symlink() or path.stat().st_size>16*1024*1024):return
        with path.open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,separators=(',',':'))+'\n')
    except (OSError,ValueError):pass


def receive(url, request_file, output):
    request_file, output = Path(request_file), Path(output)
    size = request_file.stat().st_size
    budget = limits.get('message_bytes')
    if not 0 < size <= budget: raise ValueError('Request exceeds message byte limit')
    parts = urlsplit(url)
    if parts.scheme not in ('tcp','http','https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Invalid repository transport URL')
    count = 0; digest = hashlib.sha256(); owned=False
    method=request_method(request_file);started=time.monotonic();code=None;length=None;completed=False
    def copy(source, destination, remaining=None):
        nonlocal count
        while remaining is None or remaining:
            chunk = source.read(CHUNK if remaining is None else min(CHUNK,remaining))
            if not chunk:
                if remaining: raise ValueError('Truncated repository response')
                break
            count += len(chunk)
            if count > budget: raise ValueError('Response exceeds message byte limit')
            destination.write(chunk); digest.update(chunk)
            if remaining is not None: remaining -= len(chunk)
    try:
        destination=output.open('xb');owned=True
        with destination, request_file.open('rb') as request:
            if parts.scheme == 'tcp':
                with socket.create_connection((parts.hostname,parts.port or 1542),timeout=60) as sock:
                    with sock.makefile('rb') as source:
                        if source.read(5) != bytes.fromhex('53f5c61a7b'): raise ValueError('Invalid repository TCP greeting')
                        sock.sendall(('POST / HTTP/1.1\r\nContent-Type: application/xml\r\nContent-Length: '+str(size)+'\r\n\r\n').encode())
                        for chunk in iter(lambda: request.read(CHUNK), b''): sock.sendall(chunk)
                        sock.sendall(END)
                        header = bytearray()
                        while not header.endswith(b'\r\n\r\n'):
                            chunk = source.read(1)
                            if not chunk: raise ValueError('Truncated TCP response header')
                            header += chunk
                            if len(header) > 65536: raise ValueError('Oversized TCP response header')
                        rows = header.decode('ascii').replace('\r','').split('\n')
                        if not re.fullmatch(r'HTTP/1\.[01] [0-9]{3}(?: .*)?',rows[0]): raise ValueError('Invalid TCP status line')
                        code = int(rows[0].split()[1]); length = None
                        for row in rows[1:]:
                            if not row: continue
                            key,separator,value = row.partition(':')
                            if not separator: raise ValueError('Invalid TCP header field')
                            key,value = key.strip().lower(),value.strip()
                            if key == 'content-length':
                                if length is not None or not re.fullmatch(r'[0-9]{1,19}',value): raise ValueError('Invalid Content-Length')
                                length = int(value)
                            if key == 'transfer-encoding' or key == 'content-encoding' and value.lower() != 'identity':
                                raise ValueError('Unsupported TCP response encoding')
                        if length is None: raise ValueError('Missing response Content-Length')
                        if length > budget: raise ValueError('Response Content-Length '+str(length)+' exceeds message_bytes '+str(budget))
                        copy(source,destination,length)
                        if source.read(4) != END: raise ValueError('Invalid TCP end marker')
            else:
                connection = (http.client.HTTPSConnection if parts.scheme=='https' else http.client.HTTPConnection)(parts.hostname,parts.port,timeout=60)
                try:
                    path=quote(parts.path or '/',safe="/%:@!$&'()*+,;=-._~")
                    connection.request('POST',path,request,headers={'Content-Length':str(size),'Content-Type':'application/xml'})
                    response = connection.getresponse(); code = response.status
                    lengths = [value for key,value in response.getheaders() if key.lower()=='content-length']
                    if len(lengths)>1 or lengths and not re.fullmatch(r'[0-9]{1,19}',lengths[0]):raise ValueError('Invalid HTTP Content-Length')
                    if lengths:
                        length=int(lengths[0])
                        if length>budget:raise ValueError('Response Content-Length '+str(length)+' exceeds message_bytes '+str(budget))
                    if response.getheader('Content-Encoding','identity').lower() != 'identity': raise ValueError('Unsupported HTTP response encoding')
                    if lengths and response.getheader('Transfer-Encoding'): raise ValueError('Ambiguous HTTP framing')
                    copy(response,destination)
                    if lengths and count != int(lengths[0]): raise ValueError('Truncated HTTP response')
                finally: connection.close()
        completed=True
    except BaseException as error:
        # Delete only the file created by this invocation, never a pre-existing one.
        if owned:
            output.unlink(missing_ok=True)
        if method and isinstance(error,ValueError):raise ValueError('RPC '+method+': '+str(error)) from None
        raise
    finally:
        trace_rpc(dict(rpc=method or 'unknown',request_bytes=size,response_code=code,
                       content_length=length,received_bytes=count,outcome='received' if completed else 'failed',
                       elapsed_ms=round((time.monotonic()-started)*1000)))
    return dict(code=code, file=str(output.resolve()), bytes=count, sha256=digest.hexdigest())


def extract_version(xml_file, output):
    return _extract_storage(xml_file,output,False)


def extract_context(xml_file, output):
    """updateInfo has an info sibling and a direct call_return/file child."""
    return _extract_storage(xml_file,output,True)


def _extract_storage(xml_file, output, context):
    xml_file, output = Path(xml_file), Path(output)
    xml_budget=limits.get('message_bytes')
    if xml_file.stat().st_size > xml_budget: raise ValueError('XML response exceeds message byte limit')
    if output.exists(): raise ValueError('Version output already exists')
    temporary = output.with_name(output.name+'.'+uuid.uuid4().hex+'.tmp')
    stack=[]; pending=''; padded=False; found=0; results=0; count=0; digest=hashlib.sha256()
    parser=expat.ParserCreate(namespace_separator='|')
    # Designer wraps base64 into short lines. Aggregate character callbacks so
    # CR/LF do not cause millions of tiny Python decoder calls on large replies.
    parser.buffer_text=True;parser.buffer_size=CHUNK
    try:
        with temporary.open('xb') as destination:
            def start(name, attrs):
                nonlocal found,results
                if not name.startswith(NS+'|'): raise ValueError('Invalid repository XML namespace')
                local=name.split('|',1)[1]; stack.append(local)
                if len(stack)>64:raise ValueError('Excessive repository XML nesting')
                if len(stack)==1 and local!='call_return': raise ValueError('Repository did not return call_return')
                if len(stack)==2 and local in ('info','result'): results+=1
                if local=='file':
                    valid=len(stack)==2 if context else len(stack)==3 and stack[1] in ('info','result')
                    if not valid or found: raise ValueError('Invalid or duplicate version file element')
                    found+=1
                elif 'file' in stack: raise ValueError('Nested element in base64 data')
            def characters(value):
                nonlocal pending,padded,count
                if stack[-1:] == ['file'] and (len(stack)==2 if context else len(stack)==3 and stack[1] in ('info','result')):
                    value=value.translate({ord(c):None for c in ' \t\r\n'})
                    if padded and value: raise ValueError('Data after base64 padding')
                    pending+=value; length=len(pending)//4*4
                    block,pending=pending[:length],pending[length:]
                    if not block:return
                    if '=' in block:
                        if not re.fullmatch(r'[A-Za-z0-9+/]*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)',block): raise ValueError('Invalid base64 padding')
                        padded=True
                        if pending: raise ValueError('Data after base64 padding')
                    raw=base64.b64decode(block,validate=True); count+=len(raw)
                    if count>limits.get('storage_bytes'): raise ValueError('Decoded storage exceeds byte limit')
                    destination.write(raw); digest.update(raw)
                elif any(name in ('exc','exception') for name in stack) and value.strip():
                    raise ValueError('Repository returned an exception')
            def end(name):
                if stack[-1]=='file' and pending: raise ValueError('Incomplete base64 data')
                stack.pop()
            def forbidden(*args): raise ValueError('DTD and entity declarations are forbidden')
            parser.StartElementHandler=start;parser.EndElementHandler=end;parser.CharacterDataHandler=characters
            parser.StartDoctypeDeclHandler=forbidden;parser.EntityDeclHandler=forbidden;parser.ExternalEntityRefHandler=forbidden
            with xml_file.open('rb') as source:
                consumed=0
                for chunk in iter(lambda:source.read(CHUNK),b''):
                    consumed+=len(chunk)
                    if consumed>xml_budget:raise ValueError('XML response exceeds message byte limit')
                    parser.Parse(chunk,False)
            parser.Parse(b'',True)
            if found!=1 or results!=1:raise ValueError('Missing or duplicate version result')
        FileStorage(temporary)  # Index, every record and whole-file checksum before publication.
        publish_new(temporary,output)
    except expat.ExpatError:
        raise ValueError('Malformed repository response XML') from None
    finally: temporary.unlink(missing_ok=True)
    return dict(file=str(output.resolve()),bytes=count,sha256=digest.hexdigest())


def inspect_xml(path, target=None):
    """Validate the whole reply and select one statistics entry without a DOM."""
    from decimal import Decimal, InvalidOperation
    path=Path(path);budget=limits.get('message_bytes')
    if path.stat().st_size>budget:raise ValueError('XML response exceeds message byte limit')
    if target is not None:target=str(__import__('uuid').UUID(str(target))).lower()
    parser=expat.ParserCreate(namespace_separator='|');parser.buffer_text=True
    stack=[];errors=[];matches=0;found=None;row={};root=None
    def start(name,attrs):
        nonlocal row,root,matches
        namespace,separator,name=name.rpartition('|')
        if not separator or namespace!=NS:raise ValueError('Invalid repository XML namespace')
        stack.append(name)
        if len(stack)>64:raise ValueError('Excessive repository XML nesting')
        if len(stack)==1:
            root=name
            if root not in ('call_return','call_exception'):raise ValueError('Expected repository call_return')
        if target is None:return
        if stack==['call_return','statMap','value']:row={}
        if stack[:3]!=['call_return','statMap','value']:return
        if len(stack)==4 and name=='first':
            row['id']=attrs.get('value','').lower()
            if row['id']==target:
                matches+=1
                if matches>1:raise ValueError('Duplicate object statistics')
        if len(stack)==5 and stack[3]=='second':
            value=attrs.get('value','')
            if name=='verNum':
                try:row['version']=Decimal(value)
                except InvalidOperation:raise ValueError('Invalid object version') from None
                if not row['version'].is_finite():raise ValueError('Invalid object version')
            elif name=='revised':row['captured']=value.lower()=='true'
            elif name=='revisorID':row['user']=value
            elif name=='reviseDate':row['capture_date']=value
    def text(value):
        if root=='call_exception' or any(n in ('exc','exception') for n in stack):errors.append(value)
    def end(name):
        nonlocal found
        if target is not None and stack==['call_return','statMap','value'] and row.get('id')==target:
            found=dict(row)
        stack.pop()
    def forbidden(*args):raise ValueError('DTD and entity declarations are forbidden')
    parser.StartElementHandler=start;parser.EndElementHandler=end;parser.CharacterDataHandler=text
    parser.StartDoctypeDeclHandler=forbidden;parser.EntityDeclHandler=forbidden;parser.ExternalEntityRefHandler=forbidden
    try:
        with path.open('rb') as source:
            consumed=0
            for chunk in iter(lambda:source.read(CHUNK),b''):
                consumed+=len(chunk)
                if consumed>budget:raise ValueError('XML response exceeds message byte limit')
                parser.Parse(chunk,False)
        parser.Parse(b'',True)
    except expat.ExpatError:raise ValueError('Malformed repository response XML') from None
    error=''.join(errors).strip()
    if root=='call_exception' or error:
        try:message=base64.b64decode(''.join(error.split()),validate=True).decode('utf-8')
        except (ValueError,UnicodeError):raise ValueError('Invalid repository exception') from None
        raise ValueError(message or 'Repository returned an exception')
    if found is not None:
        number=found.get('version')
        if number is not None and (not number.is_finite() or abs(number)>2**63-1):raise ValueError('Invalid object version')
        found['version']=None if number is None else int(number) if number==number.to_integral_value() else float(number)
        found.setdefault('captured',False);found.setdefault('user','');found.setdefault('capture_date','')
    return dict(found=found is not None,state=found)


def run(request):
    if request['mode'] in ('xml-check','xml-statistics'):
        return inspect_xml(request['xml_file'],request.get('object_id') if request['mode']=='xml-statistics' else None)
    output=Path(request['output_file'])
    if output.exists():raise ValueError('Response output already exists')
    with tempfile.TemporaryDirectory(prefix='crs-receive-') as folder:
        raw=Path(folder)/'response.xml'
        try:response=receive(request['url'],request['request_file'],raw)
        except http.client.HTTPException:raise ValueError('Invalid HTTP response framing') from None
        if request['mode']=='version':
            if response['code']!=200:raise ValueError('Repository returned HTTP status '+str(response['code']))
            result=extract_version(raw,output);result['code']=response['code'];return result
        if request['mode']!='exchange':raise ValueError('Unknown file exchange mode')
        # Publish without replacement, even across temporary/output filesystems.
        owned=False
        try:
            target=output.open('xb');owned=True
            with raw.open('rb') as source, target:
                for chunk in iter(lambda:source.read(CHUNK),b''):target.write(chunk)
        except BaseException:
            if owned:output.unlink(missing_ok=True)
            raise
        return dict(response,file=str(output.resolve()))


if __name__=='__main__':
    from serializer_cli import run as cli
    cli(run)
