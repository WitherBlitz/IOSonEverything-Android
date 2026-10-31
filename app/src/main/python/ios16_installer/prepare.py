"""Private preparation transaction. Caller promotes returned directory after service integration."""
from contextlib import contextmanager
import json
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import threading
from .apple import acquire_apple
from .extract import extract_image
from .images import build_image, write_payload, verify_image, verify_payload, payload_file_record
from .recipe import assemble_trees
from .resources import PROFILE, validate_resources, audit_kernel
from .persistence import create_data_store, validate_data_store, INITIAL_SHA256
from .safety import Hooks, checked_path, digest, atomic_json

_PREPARATION_LOCK = threading.Lock()

@contextmanager
def preparation_lock(base):
    if not _PREPARATION_LOCK.acquire(blocking=False): raise RuntimeError('A preparation is already active in this process')
    path = checked_path(base, '.ios16-preparation.lock'); descriptor = None
    try:
        descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(descriptor, str(os.getpid()).encode())
        yield
    finally:
        if descriptor is not None: os.close(descriptor); path.unlink()
        _PREPARATION_LOCK.release()

def copy_stream(source, destination, hooks):
    with open(source, 'rb') as incoming, open(destination, 'wb') as outgoing:
        while True:
            hooks.check(); data = incoming.read(1024 * 1024)
            if not data: break
            outgoing.write(data)
        outgoing.flush(); os.fsync(outgoing.fileno())

def prepare(base, resource_manifest, asset_root, native_root, hooks=None, opener=None):
    """Prepare an unqualified guest as ordinary UID; returns a fresh final directory.

    resource_manifest must come from trusted application assets/build metadata, never
    downloaded Apple content. Native executables must be in nativeLibraryDir. No
    active install is replaced, and no completion receipt appears before verification.
    """
    hooks = hooks or Hooks(); base = Path(base)
    if base.is_symlink(): raise ValueError('Preparation base cannot be a symlink')
    base.mkdir(parents=True, exist_ok=True); base = base.resolve()
    with preparation_lock(base):
        hooks.report('Validating source-built resources', 0)
        resources = validate_resources(resource_manifest, asset_root, native_root, hooks)
        # Need selected DMGs, extracted sources, compression spool and final image simultaneously.
        if shutil.disk_usage(base).free < 20 * 1024**3: raise OSError('At least 20 GiB free private storage required')
        downloads = checked_path(base, 'downloads')
        apple = acquire_apple(downloads, hooks, opener)
        runs = checked_path(base, 'runs'); runs.mkdir(exist_ok=True)
        run = Path(tempfile.mkdtemp(prefix='preparation-', dir=runs))
        # Incomplete runs intentionally remain private for inspection/retry cleanup by caller.
        atomic_json(run / 'state.json', {'profile':PROFILE, 'prepared':False, 'phase':'extracting'})
        extracted = {}
        for key, image_name, directory_name in (('root','rootfs.dmg','rootfs'),
                  ('os','cryptex-os.dmg','cryptex'),('app','cryptex-app.dmg','cryptex-app')):
            hooks.report('Extracting ' + key, 0)
            directory = run / directory_name
            rows, sources, all_rows = extract_image(apple[image_name], directory, resources, hooks,
                                                  root=key=='root', os_cryptex=key=='os')
            extracted[key] = (rows, sources, all_rows, directory)
        hooks.report('Applying private guest recipe', 0)
        root, system = assemble_trees(extracted, resources, resource_manifest, run/'generated', hooks)
        final = run / 'final'; final.mkdir()
        root_image = build_image(root, run/'root.apfs', 'redwood', hooks)
        build_image(system, final/'system.apfs', 'System', hooks)
        copy_stream(resources['Image'], final/'Image', hooks)
        cmdline=resource_manifest.get('cmdline','')
        if not isinstance(cmdline,str):raise ValueError('Invalid payload command line')
        kernel_record=resource_manifest['resources']['kernel']
        payload_expected={'kernel':{'bytes':kernel_record['bytes'],'sha256':kernel_record['sha256']},
                          'ramdisk':payload_file_record(root_image,hooks)}
        if cmdline:
            command=cmdline.encode()+b'\0'
            payload_expected['cmdline']={'bytes':len(command),'sha256':hashlib.sha256(command).hexdigest()}
        write_payload(final/'payload.bin',resources['kernel'],root_image,cmdline,hooks,expected_entries=payload_expected)
        persistent=resource_manifest.get('persistence') is True
        if persistent:create_data_store(final/'data.store',hooks)
        files = {}
        for name in ('Image','payload.bin','system.apfs') + (('data.store',) if persistent else ()):
            path = final/name; files[name] = {'bytes':path.stat().st_size, 'sha256':digest(path,'sha256',hooks)}
        if persistent:
            if files['data.store']['sha256'] != INITIAL_SHA256:raise ValueError('Fresh data.store initial hash differs')
            files['data.store'].update(mutable=True,sha256_is_initial_only=True)
        receipt = {'schema_version':1, 'profile':PROFILE, 'prepared':True, 'kernel_patches_verified':True,
                   'files':files, 'gui_boot_verified':False, 'input_verified':False, 'persistence_verified':False,
                   'kernel_evidence':audit_kernel(resources['kernel']),
                   'resource_manifest':resource_manifest,
                   'image_validation':{'root':verify_image(root_image, root, hooks),
                                       'system':verify_image(final/'system.apfs', system, hooks)},
                   'payload_validation':verify_payload(final/'payload.bin',payload_expected,hooks),
                   'apple_build':'20F66', 'private_apple_payloads':True,
                   'qualification':'experimental; GUI, input and persistence not verified'}
        if persistent:
            receipt['persistence']={**validate_data_store(final/'data.store'),'guest_qualified':False,
                'autosave_seconds':60,'additional_boot_arguments':'var_store=1 virt_var_store=1 virtio_blk_rw=1 var_save_ms=20000',
                'mutable_validation':'validate layout/capacity each open; initial SHA is creation provenance only'}
        if len((json.dumps(receipt,sort_keys=True,indent=2)+'\n').encode('utf-8'))>65536:
            raise ValueError('Preparation receipt exceeds Android profile reader limit')
        hooks.check(); atomic_json(final/'installation.json', receipt)
        atomic_json(run/'state.json', {'profile':PROFILE, 'prepared':True, 'phase':'prepared'})
        hooks.report('Preparation complete; experimental guest', 1)
        return final
