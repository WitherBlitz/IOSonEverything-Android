"""Unprivileged, deterministic APFS assembly. Metadata never comes from host uid/umask."""
import os
from pathlib import Path
import stat
import struct
import zlib
import hashlib
from contextlib import ExitStack
from .safety import Hooks, checked_path, safe_relative
from .vendor import mkapfs, apfs

class Tree:
    def __init__(self):self.root=mkapfs.Node('',0o40755)
    def put(self,path,node):
        parts=safe_relative(path).split('/');parent=self.root
        for part in parts[:-1]:
            if part not in parent.children:parent.children[part]=mkapfs.Node(part,0o40755)
            parent=parent.children[part]
            if not stat.S_ISDIR(parent.mode):raise ValueError('Manifest path traverses a non-directory')
        node.name=parts[-1];parent.children[parts[-1]]=node;return node
    def get(self,path):
        node=self.root
        for part in safe_relative(path).split('/'):
            node=node.children.get(part)
            if node is None:return None
        return node
    def remove(self,path):
        parts=safe_relative(path).split('/');parent=self.root
        for part in parts[:-1]:
            parent=parent.children.get(part)
            if parent is None:return
        parent.children.pop(parts[-1],None)
    def directory(self,path,mode=0o755,uid=0,gid=0):
        node=self.get(path)
        if node is None:node=self.put(path,mkapfs.Node('',stat.S_IFDIR|mode))
        if not stat.S_ISDIR(node.mode):raise ValueError('Directory collides with another inode type')
        node.mode,node.uid,node.gid=stat.S_IFDIR|mode,uid,gid;return node
    def file(self,path,source,mode=0o644,uid=0,gid=0):
        source=Path(source)
        if source.is_symlink() or not source.is_file():raise ValueError('Missing regular assembly input')
        node=self.put(path,mkapfs.Node('',stat.S_IFREG|mode,source=str(source)))
        node.uid,node.gid=uid,gid;return node
    def link(self,path,target,uid=0,gid=0,mode=0o777):
        if not target or '\0' in target:raise ValueError('Invalid guest symlink')
        node=self.put(path,mkapfs.Node('',stat.S_IFLNK|mode,target=target.encode('utf-8')));node.uid,node.gid=uid,gid;return node
    @classmethod
    def from_manifest(cls,rows,source_root,source_map=None):
        result=cls();source_map=source_map or {}
        for row in sorted(rows,key=lambda row:(row.path.count('/'),row.path)):
            if stat.S_ISDIR(row.mode):result.directory(row.path,stat.S_IMODE(row.mode),row.uid,row.gid)
            elif stat.S_ISLNK(row.mode):result.link(row.path,row.target,row.uid,row.gid,mode=stat.S_IMODE(row.mode))
            else:result.file(row.path,checked_path(source_root,source_map.get(row.path,row.path)),stat.S_IMODE(row.mode),row.uid,row.gid)
        return result

def compress_to_spool(path,spool,hooks):
    """Byte-compatible upstream zlib resource fork, with at most one64KiB piece live."""
    size=os.path.getsize(path)
    if size<=mkapfs.PIECE:
        hooks.check()
        with open(path,'rb') as stream:content=stream.read(mkapfs.PIECE)
        compressed=zlib.compress(content,9)
        if 16+len(compressed)<=mkapfs.XATTR_MAX_EMBEDDED:return 'inline',compressed
    count=mkapfs.div_up(size,mkapfs.PIECE);table_bytes=4+8*count
    start=spool.seek(0,2);spool.write(bytes(256+4+table_bytes));pieces=[];offset=table_bytes
    with open(path,'rb') as source:
        while True:
            hooks.check();piece=source.read(mkapfs.PIECE)
            if not piece:break
            compressed=zlib.compress(piece,9)
            data=compressed if len(compressed)<len(piece) else b'\xff'+piece
            pieces.append((offset,len(data)));offset+=len(data);spool.write(data)
    if len(pieces)!=count:raise ValueError('Source changed during compression')
    data_bytes=4+offset;map_offset=256+data_bytes
    resource_map=bytearray(50);struct.pack_into('>IIII',resource_map,0,256,map_offset,data_bytes,50)
    struct.pack_into('>HHH',resource_map,24,28,50,0);resource_map[30:34]=b'cmpf'
    struct.pack_into('>HHhHI',resource_map,34,0,10,1,0xffff,0)
    spool.write(resource_map);end=spool.tell()
    if mkapfs.div_up(end-start,mkapfs.BS)>=mkapfs.div_up(size,mkapfs.BS):spool.truncate(start);return None,None
    spool.seek(start);spool.write(struct.pack('>IIII',256,map_offset,data_bytes,50))
    spool.seek(start+256);spool.write(struct.pack('>I',offset));spool.write(struct.pack('<I',count))
    for offset,length in pieces:spool.write(struct.pack('<II',offset,length))
    spool.seek(end);return 'spool',(start,end-start)

class AndroidVolume(mkapfs.Volume):
    def __init__(self,*args,hooks=None,**kwargs):super().__init__(*args,**kwargs);self.hooks=hooks or Hooks()
    def collect(self):
        self.items=[];self.root.oid=mkapfs.ROOT_DIR_INO
        def walk(node,path):
            for name in sorted(node.children):
                self.hooks.check();child=node.children[name];child.oid=self.new_oid();child.path=path+name
                self.items.append((child,node.oid))
                if stat.S_ISDIR(child.mode):walk(child,child.path+'/')
        walk(self.root,'');self.data={};self.decmpfs={};self.inline={}
        files=[node for node,_ in self.items if stat.S_ISREG(node.mode)]
        for number,node in enumerate(files):
            self.hooks.check();node.size=os.path.getsize(node.source)
            if not node.size:continue
            if self.compress and not self.is_plain(node):
                kind,value=compress_to_spool(node.source,self.spool,self.hooks)
                if kind=='inline':self.inline[node.oid]=struct.pack('<IIQ',mkapfs.DECMPFS_MAGIC,mkapfs.DECMPFS_ZLIB_ATTR,node.size)+value;continue
                if kind=='spool':
                    sid=self.new_oid();offset,size=value;self.data[sid]=('spool',offset,size)
                    self.decmpfs[node.oid]=(struct.pack('<IIQ',mkapfs.DECMPFS_MAGIC,mkapfs.DECMPFS_ZLIB_RSRC,node.size),sid);continue
            self.data[node.oid]=('file',node.source,node.size)
            if number%128==0:self.hooks.report('Assembling '+self.name,number/max(1,len(files)))

def verify_image(path,tree,hooks=None):
    hooks=hooks or Hooks();container=apfs.Container(str(path))
    try:
        volumes=container.volumes()
        if len(volumes)!=1:raise ValueError('Unexpected APFS volume count')
        volume=volumes[0];root=volume.inode(2)
        if (root.mode,root.owner,root.group)!=(0o40755,0,0):raise ValueError('Synthetic APFS root permissions differ')
        expected={}
        def collect(node,path):
            for name,child in node.children.items():
                key=path+'/'+name;expected[key]=child
                if stat.S_ISDIR(child.mode):collect(child,key)
        collect(tree.root,'');seen=set()
        for name,_,oid,_ in apfs.walk(volume,2):
            hooks.check();node=expected.get(name)
            if node is None:raise ValueError('Unexpected APFS path')
            inode=volume.inode(oid)
            if (inode.mode,inode.owner,inode.group)!=(node.mode,node.uid,node.gid):raise ValueError('APFS mode/owner readback differs')
            if stat.S_ISLNK(node.mode) and inode.symlink_target_bytes()!=node.target:raise ValueError('APFS symlink readback differs')
            if stat.S_ISREG(node.mode):
                size=os.path.getsize(node.source)
                if inode.size!=size:raise ValueError('APFS file size differs')
                if size<=4*1024*1024:
                    with open(node.source,'rb') as source:
                        if inode.contents()!=source.read():raise ValueError('APFS small-file content readback differs')
            seen.add(name)
        if seen!=set(expected):raise ValueError('Missing APFS paths')
        return {'entries':len(seen),'metadata_checksums':container.blocks.cksum_checked,'metadata_readback':True,
                'small_file_contents_readback':True,'large_file_full_readback':False,'apfsck_run':False}
    finally:container.close()

def build_image(tree,path,volume_name,hooks=None,compress=True):
    hooks=hooks or Hooks();path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    checked_path(path.parent,path.name);stage=checked_path(path.parent,path.name+'.building');spool_path=checked_path(path.parent,path.name+'.spool')
    old_check=mkapfs.cancellation_point;mkapfs.cancellation_point=hooks.check
    try:
        hooks.check()
        with spool_path.open('w+b') as spool:
            volume=AndroidVolume(0,volume_name,tree.root,compress,1683900000*1000000000,spool,('fw',),hooks=hooks)
            container=mkapfs.Container([volume],256,path.name);container.layout();hooks.check();container.write(str(stage))
        verify_image(stage,tree,hooks);hooks.check()
        with stage.open('r+b') as image:os.fsync(image.fileno())
        os.replace(stage,path);return path
    finally:
        mkapfs.cancellation_point=old_check;spool_path.unlink(missing_ok=True);stage.unlink(missing_ok=True)

def _file_stamp(info):
    # Windows lstat/fstat can expose different ctime semantics. Android includes
    # change time; every platform also verifies identity, size, mtime and full hash.
    change_time=info.st_ctime_ns if os.name!='nt' else None
    return (info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,change_time)

def _unchanged_source(source):
    if (_file_stamp(os.fstat(source['stream'].fileno()))!=source['stamp'] or
        _file_stamp(source['path'].lstat())!=source['stamp']):
        raise ValueError('XNUP source changed during preparation')

def _snapshot_source(path,opened,hooks):
    path=Path(path);before=path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<2**32:
        raise ValueError('XNUP input is not a bounded nonempty regular file')
    stream=opened.enter_context(path.open('rb'));initial=os.fstat(stream.fileno())
    if _file_stamp(before)!=_file_stamp(initial):raise ValueError('XNUP source changed between stat and open')
    result={'path':path,'stream':stream,'stamp':_file_stamp(initial),'bytes':initial.st_size}
    remaining=initial.st_size;checksum=hashlib.sha256()
    while remaining:
        hooks.check();chunk=stream.read(min(remaining,1024*1024))
        if not chunk or len(chunk)>remaining:raise ValueError('XNUP source truncated during snapshot')
        checksum.update(chunk);remaining-=len(chunk)
    if stream.read(1):raise ValueError('XNUP source grew during snapshot')
    _unchanged_source(result);stream.seek(0);result['sha256']=checksum.hexdigest();return result

def _expected_payload_records(expected):
    names=['kernel','ramdisk']+(['cmdline'] if 'cmdline' in expected else [])
    if set(expected)!=set(names):raise ValueError('Unexpected XNUP entries')
    result={}
    for name in names:
        record=expected[name];size=record.get('bytes');sha=record.get('sha256')
        if type(size) is not int or not 0<size<2**32 or not isinstance(sha,str) or len(sha)!=64:
            raise ValueError('Invalid XNUP expected entry record')
        try:decoded=bytes.fromhex(sha)
        except ValueError as error:raise ValueError('Invalid XNUP expected hash') from error
        if len(decoded)!=32 or sha!=sha.lower():raise ValueError('Invalid XNUP expected hash')
        result[name]={'bytes':size,'sha256':sha}
    return result

def payload_file_record(path,hooks=None):
    """Capture an opened regular input's bounded length/hash for trusted readback."""
    with ExitStack() as opened:
        source=_snapshot_source(path,opened,hooks or Hooks())
        return {'bytes':source['bytes'],'sha256':source['sha256']}

def verify_payload(path,expected_entries,hooks=None):
    """Independent bounded XNUP parser and full entry-content readback."""
    hooks=hooks or Hooks();hooks.check();expected=_expected_payload_records(expected_entries)
    path=Path(path)
    if path.is_symlink():raise ValueError('XNUP output cannot be a symlink')
    with path.open('rb') as source:
        before=os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or not 32<=before.st_size<2**32+8:
            raise ValueError('Invalid XNUP file type/size')
        header=source.read(8)
        if len(header)!=8:raise ValueError('Truncated XNUP header')
        magic,body_bytes=struct.unpack('<II',header)
        if magic!=0x50554e58 or body_bytes!=before.st_size-8:raise ValueError('XNUP magic/size mismatch')
        verified={}
        for name,record in expected.items():
            hooks.check();entry=source.read(24)
            if len(entry)!=24:raise ValueError('Truncated XNUP entry header')
            raw_name,size,reserved=struct.unpack('<16sII',entry)
            if raw_name!=name.encode().ljust(16,b'\0') or reserved or size!=record['bytes']:
                raise ValueError('XNUP entry name/order/reserved/size differs')
            if source.tell()+size+(-size)%16+24>before.st_size:raise ValueError('XNUP entry exceeds file bounds')
            checksum=hashlib.sha256();remaining=size;command=bytearray() if name=='cmdline' else None
            if command is not None and size>2048:raise ValueError('Oversized XNUP command line')
            while remaining:
                hooks.check();chunk=source.read(min(remaining,1024*1024))
                if not chunk:raise ValueError('Truncated XNUP entry content')
                checksum.update(chunk);remaining-=len(chunk)
                if command is not None:command.extend(chunk)
            if checksum.hexdigest()!=record['sha256']:raise ValueError('XNUP full entry hash mismatch')
            if command is not None and (not command.endswith(b'\0') or b'\0' in command[:-1]):
                raise ValueError('XNUP command line terminator differs')
            padding=source.read((-size)%16)
            if padding!=bytes((-size)%16):raise ValueError('XNUP padding differs')
            verified[name]=dict(record)
        if source.read(24)!=bytes(24) or source.read(1):raise ValueError('XNUP end marker/trailing bytes differ')
        if (_file_stamp(os.fstat(source.fileno()))!=_file_stamp(before) or
            _file_stamp(path.lstat())!=_file_stamp(before)):raise ValueError('XNUP changed during readback')
    return {'bytes':before.st_size,'entries':verified,'padding_and_end_verified':True,
            'full_kernel_ramdisk_hash_readback':True,'parser':'independent bounded XNUP v1'}

def write_payload(path,kernel,ramdisk,cmdline,hooks=None,expected_entries=None):
    hooks=hooks or Hooks();path=Path(path);checked_path(path.parent,path.name)
    stage=checked_path(path.parent,path.name+'.building')
    if not isinstance(cmdline,str) or '\0' in cmdline or len(cmdline.encode())>2047:
        raise ValueError('Invalid payload command line')
    try:
        with ExitStack() as opened:
            sources={name:_snapshot_source(source,opened,hooks) for name,source in
                     (('kernel',kernel),('ramdisk',ramdisk))}
            records={name:{'bytes':source['bytes'],'sha256':source['sha256']} for name,source in sources.items()}
            command=cmdline.encode()+b'\0' if cmdline else None
            if command:records['cmdline']={'bytes':len(command),'sha256':hashlib.sha256(command).hexdigest()}
            if expected_entries is not None and _expected_payload_records(expected_entries)!=records:
                raise ValueError('XNUP source differs from trusted size/hash snapshot')
            body_bytes=sum(24+record['bytes']+(-record['bytes'])%16 for record in records.values())+24
            if body_bytes>=2**32:raise ValueError('Payload exceeds boot-shim format')
            with stage.open('w+b') as out:
                out.write(struct.pack('<II',0x50554e58,body_bytes))
                for name,record in records.items():
                    size=record['bytes'];out.write(struct.pack('<16sII',name.encode(),size,0))
                    if name=='cmdline':out.write(command)
                    else:
                        source=sources[name];hooks.report('Copying XNUP '+name,0);_unchanged_source(source)
                        remaining=size;checksum=hashlib.sha256();stream=source['stream']
                        while remaining:
                            hooks.check();chunk=stream.read(min(remaining,1024*1024))
                            if not chunk or len(chunk)>remaining:raise ValueError('XNUP source truncated during copy')
                            out.write(chunk);checksum.update(chunk);remaining-=len(chunk)
                        if stream.read(1) or checksum.hexdigest()!=record['sha256']:
                            raise ValueError('XNUP source grew or changed during copy')
                        _unchanged_source(source)
                    out.write(bytes((-size)%16))
                out.write(bytes(24));out.flush();os.fsync(out.fileno())
            verify_payload(stage,records,hooks)
            for source in sources.values():_unchanged_source(source)
        hooks.check();os.replace(stage,path);return path
    finally:stage.unlink(missing_ok=True)
