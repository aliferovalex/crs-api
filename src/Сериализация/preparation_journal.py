"""Atomic, versioned preparation journals; no repository mutation or credentials."""
import base64
import copy
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import uuid

import repository_cache
import resource_limits as limits

MAX_PACKET=256*1024*1024
PHASES={'Подготовка','Готово','НетИзменений','Отменено','ЗахватыНеОсвобождены',
        'Отправка','ИсходНеизвестен','Помещено','ПомещеноОсноваНеОбновлена','Восстановлено'}

def process_identity(pid):
    if os.name=='nt':
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:
            if ctypes.get_last_error()==87:return None
            raise ValueError('Cannot check preparation owner process')
        try:
            created=wintypes.FILETIME();exited=wintypes.FILETIME();system=wintypes.FILETIME();user=wintypes.FILETIME()
            kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
            kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
            status=wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle,ctypes.byref(status)) or status.value!=259:return None
            if not kernel.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(exited),ctypes.byref(system),ctypes.byref(user)):raise ValueError('Cannot identify preparation owner process')
            return dict(pid=pid,born=(created.dwHighDateTime<<32)|created.dwLowDateTime)
        finally:kernel.CloseHandle(handle)
    try:
        text=Path('/proc/'+str(pid)+'/stat').read_text()
        fields=text[text.rfind(')')+2:].split()
        if fields[0]=='Z':return None
        return dict(pid=pid,born=int(fields[19]))
    except FileNotFoundError:return None

def alive(identity):return identity is not None and process_identity(identity['pid'])==identity

def digest(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
def atomic(path,value):
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temp.open('xb') as stream:stream.write(encoded(value));stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)

@contextmanager
def locked(directory):
    # Keep the inode: unlinking a stale lock races with a new lock owner.
    # Kernel locks are released even when the writer is forcibly terminated.
    path=directory/'write.lock'
    with path.open('a+b') as stream:
        if stream.tell()==0:stream.write(b'\0');stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            acquire=lambda:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            release=lambda:msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            acquire=lambda:fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            release=lambda:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
        try:
            acquire()
        except OSError:raise ValueError('Preparation journal is being written') from None
        try:yield
        finally:
            stream.seek(0);release()

def read(directory):
    path=directory/'state.json'
    if path.stat().st_size>4*1024*1024:raise ValueError('Preparation journal is oversized')
    envelope=json.loads(path.read_text(encoding='utf-8'))
    data=envelope['data']
    if envelope['sha256']!=digest(encoded(data)) or data['schema']!=1:raise ValueError('Preparation journal checksum/schema mismatch')
    if data['operation_id']!=directory.name:raise ValueError('Preparation journal identity mismatch')
    if 'packet_sha256' in data:
        packet=directory/'packet.bin'
        if not packet.is_file() or packet.stat().st_size>limits.get('packet_bytes',MAX_PACKET) or limits.file_digest(packet)!=data['packet_sha256']:raise ValueError('Preparation packet checksum mismatch')
    validate(data['snapshot'])
    return data

def write(directory,data):atomic(directory/'state.json',dict(data=data,sha256=digest(encoded(data))))

def validate(snapshot):
    if snapshot['state'] not in PHASES:raise ValueError('Invalid preparation state')
    ids=set()
    for row in snapshot['captures']:
        oid=str(uuid.UUID(row['id']))
        if oid in ids or not isinstance(row['new'],bool) or not isinstance(row['version'],int):raise ValueError('Invalid preparation captures')
        if not isinstance(row['date'],str):raise ValueError('Invalid preparation capture date')
        ids.add(oid)
    if len(set(snapshot['order']))!=len(snapshot['order']) or not set(snapshot['order'])<=ids:raise ValueError('Invalid preparation capture order')
    for row in snapshot['created']:
        uuid.UUID(row['id'])
        if len(row['local'])!=40:raise ValueError('Invalid created-object version')
        bytes.fromhex(row['local'])

def binding(request,cache_directory):
    state,_,_=repository_cache.Cache(cache_directory).load()
    return dict(repository_id=state['repository_id'],root_id=state['root_id'],platform=state['platform'],user_id=str(uuid.UUID(request['user_id'])))

def run(request):
    owner=process_identity(os.getppid())
    if owner is None:raise ValueError('Cannot identify preparation caller')
    mode=request['mode']
    if mode=='create':
        cache=Path(request['cache_directory']).resolve();bound=binding(request,cache)
        state,_,_=repository_cache.Cache(cache).load()
        if state['repository_version']!=request['snapshot']['version']:raise ValueError('Cache changed before preparation journal creation')
        validate(request['snapshot'])
        directory=cache/'preparations'/uuid.uuid4().hex;directory.mkdir(parents=True)
        data=dict(schema=1,operation_id=directory.name,revision=0,owner=owner,binding=bound,cache_directory=str(cache),snapshot=request['snapshot'])
        with locked(directory):write(directory,data)
    else:
        directory=Path(request['directory']).resolve()
        if len(directory.name)!=32 or any(c not in '0123456789abcdef' for c in directory.name):raise ValueError('Invalid preparation directory')
        with locked(directory):
            data=read(directory)
            if directory.parent!=Path(data['cache_directory'])/'preparations':raise ValueError('Preparation directory differs from its cache')
            if mode=='claim':
                expected=binding(request,data['cache_directory'])
                if data['binding']!=expected or repository_cache.identity(dict(repository_info=request['repository_info']))!=expected['repository_id'] or request['platform']!=expected['platform']:raise ValueError('Preparation belongs to another repository/platform/user')
                if alive(data['owner']):raise ValueError('Preparation owner process is still running')
                data['owner']=owner
                phase=data['snapshot']['state']
                if phase=='Отправка':data['snapshot']['state']='ИсходНеизвестен'
                elif phase in ('Готово','Подготовка','НетИзменений'):data['snapshot']['state']='Восстановлено'
            elif mode=='save':
                if data['owner']!=owner or request['revision']!=data['revision']:raise ValueError('Preparation journal changed or has another owner')
                validate(request['snapshot']);data['snapshot']=request['snapshot']
                if request.get('packet'):
                    raw=base64.b64decode(request['packet'],validate=True)
                    if not raw or len(raw)>MAX_PACKET:raise ValueError('Preparation packet is oversized/empty')
                    packet=directory/'packet.bin';checksum=digest(raw)
                    if 'packet_sha256' in data and data['packet_sha256']!=checksum:raise ValueError('Preparation packet is immutable')
                    if packet.exists():
                        if digest(packet.read_bytes())!=checksum:raise ValueError('Preparation packet is immutable')
                    else:
                        with packet.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
                    data['packet_sha256']=checksum
            else:raise ValueError('Unknown preparation journal mode')
            data['revision']+=1;write(directory,data)
    result=dict(directory=str(directory),revision=data['revision'],snapshot=data['snapshot'],binding=data['binding'],cache_directory=data['cache_directory'])
    if mode=='claim':
        # OneScript coerces ISO JSON strings to dates; preserve the raw token.
        result['snapshot']=copy.deepcopy(data['snapshot'])
        for row in result['snapshot']['captures']:
            row['date_token']='@'+row.pop('date')
    if mode=='claim' and 'packet_sha256' in data:result['packet']=base64.b64encode((directory/'packet.bin').read_bytes()).decode()
    return result

if __name__=='__main__':
    from serializer_cli import run as cli
    cli(run)
