"""Opt-in owned data archive format; no Apple bytes, disk reset or qualification claim."""
import os
from pathlib import Path
import stat
import struct
import zlib
from .safety import Hooks, checked_path

STORE_AT = 65536
SLOT_BYTES = 1 << 30
STORE_BYTES = STORE_AT + 2 * SLOT_BYTES
MAGIC = b'IOS16VARSTORE\0\0\0'
INITIAL_SHA256 = '813bc9411fcabdd759f1e5fa6b261d24b951323e13428884597d635fa4ee0c03'
PERSISTENT_KERNEL_SHA256 = 'b4ee84955dd66d29feb20ec9a7578e9e540046dbaafea372502ab41fdc39eec8'
VAR_STORE_SHA256 = '18eddf412a95758124e58d07d0aceb364eca7fdd5dd38d9444aaf5606078399e'
PERSISTENT_INIT_SHA256 = '085056fc6164d2e300b67ea1dff9289918a1c28bbed2d2b0c57ca3259a5234e4'
SOURCE_HASHES = {
    'kernel-persistence.patch':'e735eb3ddf2ff6fd98e2246bf772c186e96bb25656271c2fd392c5e537fc6aed',
    'var_store.c':'0ce819b318a47ddd092a3642996e750f95cf7ee66c5efdaddb311a67be2735c1',
    'varstore-disk.h':'c2a24c4688355bb3427159bfceb0f7c7b003d65ab1a90c17f9481dc0a37e71bb',
    'var-store-hardening.patch':'27d66370e8ec0a6a84969159a26829da3984dab9f2ee9214b32fafeffcd8104e',
    'init.c':'df70a9e227274ad90206bb91d888e292ddbce3a75d6cf014232a6ab37a3d5686',
    'mini.c':'4aafe4461e79a503336fc149c263d96fef7d5e9d28eaf7375ce968f838c4aa68',
    'mini.h':'7f633455ab782794b11e2daa04480fe27bd8d8eb4f470e1e7bcbfc77246f09cb',
    'start.S':'75024af4f60a89ff82269a7076be303bcb50779f9f1d4ef504231bcf4ea1012c'}

def validate_persistence(manifest):
    enabled = manifest.get('persistence', False)
    if type(enabled) is not bool: raise ValueError('Persistence must be an explicit boolean')
    if not enabled: return False
    expected = {'kernel':PERSISTENT_KERNEL_SHA256,'init':PERSISTENT_INIT_SHA256,'var_store':VAR_STORE_SHA256}
    entries = manifest.get('resources', {})
    for name, sha in expected.items():
        if entries.get(name, {}).get('sha256') != sha:
            raise ValueError('Unapproved persistence artifact: ' + name)
    if entries['var_store'].get('source', {}).get('commit') != '05afc43591d81ee2fe3cda943b728b39c3bda257':
        raise ValueError('Persistence helper source pin differs')
    audit = manifest.get('persistence_source_audit', {})
    if (audit.get('verification') != 'source-build-and-binary-audit' or
        audit.get('kernel_source_commit') != '1603ed003665a07753c260b76929c4a3a1796681' or
        audit.get('userland_source_commit') != '05afc43591d81ee2fe3cda943b728b39c3bda257' or
        any(audit.get(name + '_sha256') != sha for name,sha in expected.items()) or
        any(audit.get('source_hashes', {}).get(name) != sha for name,sha in SOURCE_HASHES.items())):
        raise ValueError('Persistence build/source audit is absent or mismatched')
    return True

def superblock():
    header = struct.pack('<16sIIQQQII',MAGIC,1,56,STORE_BYTES,SLOT_BYTES,STORE_AT,2,0)
    header = header[:-4] + struct.pack('<I',zlib.crc32(header))
    return header + bytes(4096-len(header))

def _mark_sparse(fd):
    if os.name == 'nt':
        # Windows test host only. Android ftruncate naturally creates sparse holes.
        import ctypes
        import msvcrt
        returned = ctypes.c_uint32()
        function = ctypes.windll.kernel32.DeviceIoControl
        function.argtypes = [ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,
                             ctypes.c_void_p,ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32),ctypes.c_void_p]
        function.restype = ctypes.c_int
        if not function(msvcrt.get_osfhandle(fd),0x900c4,None,0,None,0,ctypes.byref(returned),None):
            raise OSError('Cannot mark test-host data.store sparse')

def validate_data_store(path):
    path = Path(path); checked_path(path.parent,path.name)
    fd = os.open(str(path),os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != STORE_BYTES:
            raise ValueError('Dedicated data.store capacity/type mismatch')
        header = os.read(fd,STORE_AT)
        if len(header) != STORE_AT: raise ValueError('Truncated data.store superblock area')
        fields = struct.unpack('<16sIIQQQII',header[:56])
        if fields[:-1] != (MAGIC,1,56,STORE_BYTES,SLOT_BYTES,STORE_AT,2):
            raise ValueError('Dedicated data.store identity/layout mismatch')
        if zlib.crc32(header[:52]+bytes(4)) != fields[-1] or any(header[56:]):
            raise ValueError('Dedicated data.store header CRC/reserved bytes differ')
        # Slot headers/bodies are mutable and validated by the guest archive reader.
        return {'bytes':STORE_BYTES,'slot_bytes':SLOT_BYTES,'slots':2,'store_at':STORE_AT,
                'superblock_bytes':4096,'device':'/dev/rrvblk1','mutable':True,
                'sha256_is_initial_only':True,'layout_verified':True}
    finally: os.close(fd)

def create_data_store(path,hooks=None):
    """Create only a fresh owned sparse disk; the caller hashes it before receipt commit."""
    hooks = hooks or Hooks(); hooks.check(); path = Path(path); checked_path(path.parent,path.name)
    fd = os.open(str(path),os.O_CREAT|os.O_EXCL|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0),0o600)
    complete = False
    try:
        _mark_sparse(fd); header=superblock()
        if os.write(fd,header) != len(header): raise OSError('Short data.store header write')
        hooks.check(); os.ftruncate(fd,STORE_BYTES); os.fsync(fd); hooks.check()
        for offset in (STORE_AT,STORE_AT+SLOT_BYTES):
            os.lseek(fd,offset,os.SEEK_SET)
            if os.read(fd,4096) != bytes(4096): raise ValueError('New data.store slot is not empty')
        metadata=validate_data_store(path); hooks.check(); complete=True; return metadata
    finally:
        os.close(fd)
        if not complete:path.unlink(missing_ok=True)
