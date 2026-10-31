"""Pinned official Apple ZIP member acquisition. No full IPSW or third-party images."""
import io
import os
from pathlib import Path
import plistlib
import struct
import urllib.parse
import urllib.request
import zipfile
import zlib
from .safety import Hooks, atomic_json, checked_path, digest

URL=('https://updates.cdn-apple.com/2023SpringFCS/fullrestores/032-85130/'
     '6AB0D10A-8AF9-4F6C-8CF5-A1B315CABE88/iPhone10,3,iPhone10,6_16.5_20F66_Restore.ipsw')
IPSW_BYTES=6165698198
MANIFEST_SHA256='7dd041dc7ac05f2e1f041013024f9062b8166d916c708ff8b46aca5e089e091f'
MEMBERS={
 'BuildManifest.plist':{'output':'BuildManifest.plist','bytes':449650,'compressed':27284,'method':8,'offset':6011350361,'sha256':MANIFEST_SHA256},
 '096-04088-077.dmg':{'output':'rootfs.dmg','bytes':4728546953,'compressed':4728546953,'method':0,'offset':94323815,
  'sha384':'14a9e57f31e1f64bac1fbff2d20d34d20210530b03e700d6279a0ef7a7a370b27ac17cd257c880e60bd16e2b26bc754f'},
 '096-04666-078.dmg':{'output':'cryptex-os.dmg','bytes':2726297600,'compressed':1094826706,'method':8,'offset':4822870835,
  'sha384':'f778d9abf553a111a3eb36d7e2c5b18569d4d7ca119d20156c8e0a910469e79be720e1c217f1f7af98a73ecd62bdf411'},
 '096-03536-083.dmg':{'output':'cryptex-app.dmg','bytes':10485760,'compressed':2379179,'method':8,'offset':0,
  'sha384':'cd6c42de4466b3746c86004aac419569189ef75408bb083a86b16a4265a7cd7d38e7dc86b0fcb68c9ea932fa52198773'},
}

def official_url(url):
    parsed=urllib.parse.urlsplit(url)
    return parsed.scheme=='https' and parsed.hostname=='updates.cdn-apple.com' and not parsed.username and not parsed.password

class RangeReader(io.RawIOBase):
    def __init__(self,url,size,hooks=None,opener=None):
        if not official_url(url) or not 1<=size<=16*1024**3:raise ValueError('Unexpected firmware origin or archive size')
        self.url,self.size,self.hooks=url,size,hooks or Hooks()
        self.opener=opener or (lambda req:urllib.request.urlopen(req,timeout=60))
        self.position=0
    def seekable(self):return True
    def readable(self):return True
    def tell(self):return self.position
    def seek(self,offset,whence=0):
        position=offset if whence==0 else self.position+offset if whence==1 else self.size+offset if whence==2 else -1
        if not 0<=position<=self.size:raise ValueError('Archive seek out of bounds')
        self.position=position;return position
    def read(self,size=-1):
        self.hooks.check()
        size=self.size-self.position if size<0 else min(size,self.size-self.position)
        if size>8*1024*1024:raise ValueError('Oversized archive range')
        if not size:return b''
        start,end=self.position,self.position+size-1
        request=urllib.request.Request(self.url,headers={'Range':f'bytes={start}-{end}','Accept-Encoding':'identity','User-Agent':'IOSonEverything/ios16-preparation'})
        with self.opener(request) as response:
            if response.status!=206 or response.headers.get('Content-Range')!=f'bytes {start}-{end}/{self.size}':
                raise ValueError('Server did not honor exact HTTP range')
            if not official_url(response.geturl()):raise ValueError('Firmware redirect left original Apple publisher')
            if response.headers.get('Content-Length') is not None and int(response.headers['Content-Length'])!=size:
                raise ValueError('Wrong range Content-Length')
            chunks=[];remaining=size
            while remaining:
                self.hooks.check();data=response.read(min(remaining,1024*1024))
                if not data:raise ConnectionError('Truncated firmware range')
                if len(data)>remaining:raise ValueError('Oversized firmware response')
                chunks.append(data);remaining-=len(data)
        self.position+=size;return b''.join(chunks)

class Archive:
    def __init__(self,url,size,hooks=None,opener=None):
        self.hooks=hooks or Hooks();self.reader=RangeReader(url,size,self.hooks,opener)
        self.zip=zipfile.ZipFile(self.reader)
    def entry(self,name):
        matches=[info for info in self.zip.infolist() if info.filename==name]
        if len(matches)!=1:raise ValueError('Missing or duplicate selected ZIP member')
        info=matches[0]
        if info.flag_bits&0x2041 or info.compress_type not in (0,8):raise ValueError('Unsupported encrypted/compressed firmware member')
        self.reader.seek(info.header_offset);header=self.reader.read(30)
        if len(header)!=30 or header[:4]!=b'PK\x03\x04':raise ValueError('Invalid ZIP local header')
        flags,method=struct.unpack_from('<HH',header,6)
        crc,compressed,size=struct.unpack_from('<III',header,14)
        if (flags,method)!=(info.flag_bits,info.compress_type):raise ValueError('ZIP central/local flags or method mismatch')
        namesize,extra=struct.unpack_from('<HH',header,26)
        if namesize>1024 or extra>65535:raise ValueError('Invalid ZIP local-header lengths')
        limit=min([self.zip.start_dir]+[entry.header_offset for entry in self.zip.infolist()
                                      if entry.header_offset>info.header_offset])
        offset=info.header_offset+30+namesize+extra
        if offset+info.compress_size>limit:raise ValueError('Selected ZIP member exceeds its data region')
        actual=self.reader.read(namesize).decode('utf-8')
        if actual!=name:raise ValueError('ZIP central/local name mismatch')
        local_extra=self.reader.read(extra)
        zip64=None;position=0
        while position<len(local_extra):
            if len(local_extra)-position<4:raise ValueError('Truncated ZIP local extra header')
            tag,length=struct.unpack_from('<HH',local_extra,position);position+=4
            if length>len(local_extra)-position:raise ValueError('Truncated ZIP local extra data')
            if tag==1:
                # APPNOTE 4.5.3: a local ZIP64 entry contains both sizes, even for small files.
                if zip64 is not None or length!=16:raise ValueError('Invalid or duplicate local ZIP64 sizes')
                zip64=struct.unpack_from('<QQ',local_extra,position)
            position+=length
        if compressed==0xffffffff or size==0xffffffff:
            if zip64 is None:raise ValueError('Missing local ZIP64 sizes')
            zsize,zcompressed=zip64
            if size!=0xffffffff and size!=zsize or compressed!=0xffffffff and compressed!=zcompressed:
                raise ValueError('Conflicting local ZIP64 sizes')
            size,compressed=zsize,zcompressed
        elif zip64 is not None:raise ValueError('Unexpected local ZIP64 size extra')
        if flags&8:
            # Streamed writers use zero placeholders; backfilled values must still agree.
            if crc not in (0,info.CRC) or compressed not in (0,info.compress_size) or size not in (0,info.file_size):
                raise ValueError('ZIP central/local descriptor metadata mismatch')
            self.reader.seek(offset+info.compress_size)
            wide=zip64 is not None or max(info.compress_size,info.file_size)>=0xffffffff
            expected=struct.pack('<IQQ' if wide else '<III',info.CRC,info.compress_size,info.file_size)
            trailer=self.reader.read(min(len(expected)+4,limit-self.reader.tell()))
            # APPNOTE 4.3.9: signature is optional; a CRC can itself equal that signature.
            if not (trailer[:len(expected)]==expected or trailer==b'PK\x07\x08'+expected):
                raise ValueError('Missing or inconsistent ZIP data descriptor')
        elif (crc,compressed,size)!=(info.CRC,info.compress_size,info.file_size):
            raise ValueError('ZIP central/local CRC or size mismatch')
        return info,offset
    def acquire(self,name,destination,sha384=None,sha256=None):
        if not sha384 and not sha256:raise ValueError('A pinned cryptographic member digest is required')
        info,offset=self.entry(name);path=Path(destination);path.parent.mkdir(parents=True,exist_ok=True)
        checked_path(path.parent,path.name)
        algorithm,expected=('sha384',sha384) if sha384 else ('sha256',sha256)
        if path.is_file() and path.stat().st_size==info.file_size and digest(path,algorithm,self.hooks)==expected:return path
        part=checked_path(path.parent,path.name+'.compressed.part')
        decoded=checked_path(path.parent,path.name+'.decoding')
        have=part.stat().st_size if part.exists() else 0
        if have>info.compress_size:part.unlink();have=0
        self.reader.seek(offset+have)
        with part.open('ab' if have else 'wb') as out:
            while have<info.compress_size:
                self.hooks.check();data=self.reader.read(min(info.compress_size-have,1024*1024))
                out.write(data);have+=len(data);self.hooks.report('Downloading '+name,have/max(1,info.compress_size))
            out.flush();os.fsync(out.fileno())
        inflater=zlib.decompressobj(-15) if info.compress_type==8 else None
        crc=0;written=0
        try:
            with part.open('rb') as source,decoded.open('wb') as out:
                while True:
                    self.hooks.check();chunk=source.read(1024*1024)
                    if not chunk:break
                    while chunk:
                        data=inflater.decompress(chunk,1024*1024) if inflater else chunk
                        chunk=inflater.unconsumed_tail if inflater else b''
                        written+=len(data)
                        if written>info.file_size:raise ValueError('Inflated member exceeds its declared size')
                        crc=zlib.crc32(data,crc);out.write(data)
                        self.hooks.report('Decoding '+name,written/max(1,info.file_size))
                if inflater and (not inflater.eof or inflater.unused_data):raise ValueError('Truncated or trailing deflate data')
                out.flush();os.fsync(out.fileno())
            if written!=info.file_size or crc!=info.CRC or digest(decoded,algorithm,self.hooks)!=expected:
                raise ValueError('Selected firmware size, ZIP CRC or cryptographic digest mismatch')
            self.hooks.check();os.replace(decoded,path);part.unlink();return path
        except InterruptedError:raise
        except Exception:
            decoded.unlink(missing_ok=True);part.unlink(missing_ok=True);raise

def acquire_apple(directory,hooks=None,opener=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True);hooks=hooks or Hooks()
    archive=Archive(URL,IPSW_BYTES,hooks,opener)
    for name,spec in MEMBERS.items():
        info,_=archive.entry(name)
        if (info.file_size,info.compress_size,info.compress_type,info.header_offset)!=(spec['bytes'],spec['compressed'],spec['method'],spec['offset']):
            raise ValueError('Selected ZIP member differs from pinned 20F66 archive')
    spec=MEMBERS['BuildManifest.plist']
    manifest_path=archive.acquire('BuildManifest.plist',directory/spec['output'],sha256=MANIFEST_SHA256)
    manifest=plistlib.loads(manifest_path.read_bytes())
    if manifest.get('ProductVersion')!='16.5' or manifest.get('ProductBuildVersion')!='20F66' or set(manifest.get('SupportedProductTypes',[]))!={'iPhone10,3','iPhone10,6'}:
        raise ValueError('Apple BuildManifest identity mismatch')
    components={}
    for identity in manifest['BuildIdentities']:
        if identity['Info'].get('DeviceClass')!='d22ap':continue
        for component in identity['Manifest'].values():
            name=component.get('Info',{}).get('Path')
            if name in MEMBERS and name.endswith('.dmg'):
                value=component.get('Digest')
                if not isinstance(value,bytes) or len(value)!=48 or value.hex()!=MEMBERS[name]['sha384']:
                    raise ValueError('Selected member SHA384 differs from Apple BuildManifest')
                components[name]=value.hex()
    if set(components)!={name for name in MEMBERS if name.endswith('.dmg')}:raise ValueError('Incomplete selected Apple component digests')
    result={}
    for name,spec in MEMBERS.items():
        if not name.endswith('.dmg'):continue
        result[spec['output']]=archive.acquire(name,directory/spec['output'],sha384=spec['sha384'])
    atomic_json(directory/'acquisition.json',{'url':URL,'build':'20F66','manifest_sha256':MANIFEST_SHA256,'sha384':components,'complete':True})
    return result
