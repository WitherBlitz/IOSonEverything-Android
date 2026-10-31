from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import stat

def safe_relative(value):
    if not isinstance(value,str) or not value or value.startswith(('/', '-','@')) or '\\' in value or ':' in value or any(ord(c)<32 or ord(c)==127 for c in value):
        raise ValueError('Unsafe relative path')
    if any(part in ('','.','..') for part in value.split('/')):raise ValueError('Unsafe relative path component')
    return value

def checked_path(base,value):
    safe_relative(value)
    base=Path(base).resolve();path=base
    for part in value.split('/'):
        path=path/part
        if path.is_symlink():raise ValueError('Symlink in private host path')
    if path.resolve().is_relative_to(base):return path
    raise ValueError('Private path escaped its base')

@dataclass(frozen=True)
class Row:
    mode:int
    uid:int
    gid:int
    path:str
    target:str=''

def manifest_rows(text):
    rows=[];seen=set()
    for line in text.splitlines():
        if not line:continue
        fields=line.split('\t')
        if len(fields) not in (4,5):raise ValueError('Malformed metadata manifest row')
        mode,uid,gid=int(fields[0],8),int(fields[1]),int(fields[2])
        path=safe_relative(fields[3]);target=fields[4] if len(fields)==5 else ''
        if path in seen or stat.S_IFMT(mode) not in (stat.S_IFDIR,stat.S_IFREG,stat.S_IFLNK) or mode&~0o177777 or not 0<=uid<=0xffffffff or not 0<=gid<=0xffffffff:
            raise ValueError('Duplicate path, invalid owner or unsupported inode type')
        if stat.S_ISLNK(mode) and (not target or '\x00' in target or '\n' in target):raise ValueError('Invalid guest symlink target')
        seen.add(path);rows.append(Row(mode,uid,gid,path,target))
    return rows

@dataclass
class Hooks:
    cancelled: object=lambda:False
    progress: object=lambda *args:None
    def check(self):
        if self.cancelled():raise InterruptedError('iOS16 preparation cancelled')
    def report(self,*args):self.check();self.progress(*args)

def digest(path,algorithm='sha256',hooks=None):
    result=hashlib.new(algorithm)
    with open(path,'rb') as source:
        while True:
            if hooks:hooks.check()
            data=source.read(1024*1024)
            if not data:break
            result.update(data)
    return result.hexdigest()

def atomic_json(path,value):
    path=Path(path);temporary=path.with_name(path.name+'.tmp')
    with temporary.open('w',encoding='utf-8',newline='\n') as out:
        json.dump(value,out,sort_keys=True,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
    os.replace(temporary,path)
