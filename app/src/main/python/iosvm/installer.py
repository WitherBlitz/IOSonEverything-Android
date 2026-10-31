# SPDX-License-Identifier: GPL-3.0-or-later
"""Private iOS 14 acquisition -> restore -> CPU-renderer patch -> promotion.

Normal guest launches do not load Python. All emulator disks live under the
Android application's own files directory; host/device partitions are untouched.
"""
from collections import deque
from functools import partial
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import threading
import time
import zipfile

from .acquisition import (acquire, promote, sha256, recover_installation, cleanup_staging,
                          find_restore_checkpoint)
from .firmware import select_identity, rebuild_sep, personalize
from .ramdisk import patch_ramdisk
from .restore import RestoreClient, mux_connect
from .tickets import forge
from .vendor.muxd import Muxd

PROFILE = 'iphone11-18A5351d-cpu-v1'
IPSW_URL = ('https://updates.cdn-apple.com/2020SummerSeed/fullrestores/001-35886/'
            '5FE9BE2E-17F8-41C8-96BB-B76E2B225888/iPhone11,8,iPhone12,1_14.0_18A5351d_Restore.ipsw')
IPSW_HASH = '706742ed60327a5247c29ccc5bf7e6ce9bbf11dd30a468f8f6fc9da76bdca96d'
ROM_URL = 'https://securerom.fun/resources/SEPROM/AppleSEPROM-Cebu-B1'
ROM_HASH = 'e3b11f624e3382a203c1f781b889b407554668936c86b0e2d41d229976317a1b'
# Public firmware research material, verified on the exact build's Apple Wiki page.
# https://theapplewiki.com/wiki/Keys:AzulSeed_18A5351d_(iPhone12,1)
SEP_IV = bytes.fromhex('017a328b048aab2edcc4cfe043c2d844')
SEP_KEY = bytes.fromhex('a55e67143d57938e37ec6b83ba9e181c0d24bd0a6a14f9f39752b967a9c45cfc')
ASSET_HASHES = {
    'ticket-template.plist': '26dfa587bd7d528770fe2a2957b7cc3c5cb384cf7127bb4157e327230055db7c',
    'inferno_patcher': 'afdd06c60da1c4927aec79850cf846a192a4336404232974004c0e674fe32b7b',
    'inferno_fs_patcher': '716f54ce4b2ad4f79c3914c2957a617e69eeea2884d25cecb27a134eeedcb8c6',
}
DISKS = {'root': 32 << 30, 'firmware': 8 << 20, 'syscfg': 128 << 10,
         'ctrl_bits': 8 << 10, 'nvram': 8 << 10, 'effaceable': 4 << 10,
         'panic_log': 1 << 20, 'sep_nvram': 64 << 10, 'sep_ssc': 128 << 10}
BOOT_FILES = ('root', 'firmware', 'syscfg', 'ctrl_bits', 'nvram', 'effaceable',
              'panic_log', 'sep_nvram', 'sep_ssc', 'kernel', 'dtb', 'trustcache',
              'sep_fw', 'sep_rom', 'vm.properties')


def record_installation(stage, console):
    text = '\n'.join(console)
    required = ['*** PATCHER: the patcher exited with 0',
                '*** PATCHER: saved SEP firmware ready',
                '*** PATCHER: unmount /mnt9 result=0',
                '*** PATCHER: unmount /mnt8 result=0',
                '*** PATCHER: unmount /mnt7 result=0',
                '*** PATCHER: five services switched off',
                '*** PATCHER: done, the machine can be reset now']
    if not all(marker in text for marker in required) or '*** PATCHER: the patcher exited with -' in text:
        raise ValueError('Guest filesystem patching has not succeeded')
    for line in console:
        if '*** PATCHER: the patcher exited with ' in line and not line.rstrip().endswith('with 0'):
            raise ValueError('Guest filesystem patcher failed')
    root = stage / 'root'
    if root.stat().st_size != DISKS['root']:
        raise ValueError('Restored guest root disk has an invalid size')
    with root.open('rb') as source:
        header = source.read(8192)
    if header[512:520] != b'EFI PART' and header[4096:4104] != b'EFI PART':
        raise ValueError('Guest restore did not create a GPT disk')
    receipt = {'profile': PROFILE, 'restored': True, 'patched': True,
               'files': {name: (stage / name).stat().st_size for name in BOOT_FILES},
               'static_sha256': {name: sha256(stage / name) for name in
                                 ('kernel', 'dtb', 'trustcache', 'sep_fw', 'sep_rom')},
               'prepared_at': time.time(), 'gui_boot_verified': False}
    with (stage / 'installation.json').open('w') as target:
        json.dump(receipt, target, indent=2)
        target.flush(); os.fsync(target.fileno())


def record_restore_checkpoint(stage):
    if (stage / 'root').stat().st_size != DISKS['root']:
        raise ValueError('Restored guest root disk has an invalid size')
    with (stage / 'root').open('rb') as root:
        header = root.read(8192)
    if header[512:520] != b'EFI PART' and header[4096:4104] != b'EFI PART':
        raise ValueError('Restore did not create a GPT disk')
    data = {'profile': PROFILE, 'restored': True, 'patched': False,
            'files': {name: (stage / name).stat().st_size for name in BOOT_FILES + ('ramdisk',)},
            'static_sha256': {name: sha256(stage / name) for name in
                              ('kernel', 'dtb', 'trustcache', 'sep_fw', 'sep_rom', 'ramdisk')}}
    temporary = stage / 'restore-complete.json.part'
    with temporary.open('w') as target:
        json.dump(data, target, indent=2)
        target.flush(); os.fsync(target.fileno())
    os.replace(temporary, stage / 'restore-complete.json')
    if os.name != 'nt':
        directory = os.open(stage, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def command(engine, stage, resources, usb_path, ramdisk, patch_only=False):
    boot_mode = 'exit_recovery' if patch_only else 'enter_recovery'
    args = [str(engine), '-L', str(resources / 'qemu-data'),
            '-accel', 'tcg,thread=multi,tb-size=256',
            '-M', ('t8030,usb-uplink-type=inferno,usb-uplink-addr=unix:%s,'
                   'trustcache=trustcache,sep-fw=sep_fw,sep-rom=sep_rom,'
                   'kaslr-off=true,boot-mode=%s,gpu=off' % (usb_path, boot_mode)),
            '-kernel', 'kernel', '-dtb', 'dtb', '-initrd', ramdisk,
            # exit_recovery avoids the engine's implicit nand-enable-reformat=1,
            # which otherwise exposes a dummy storage device. Keep the ramdisk
            # as root explicitly so this remains a patch-only recovery boot.
            '-append', (('rd=md0 ' if patch_only else '') +
                        'tlto_us=-1 mtxspin=-1 agm-genuine=1 agm-authentic=1 agm-trusted=1 '
                        'serial=3 wdt=-1 launchd_unsecure_cache=1 -vm_compressor_wk_sw'),
            # One AP plus the SEP during restore: reduce concurrent guest USB
            # driver activity while investigating the controller's DART fault.
            '-smp', '2', '-m', '3G', '-display', 'none', '-monitor', 'none',
            '-qmp', 'unix:%s,server=on,wait=off' % Path(usb_path).with_name('ios-install-qmp.sock'),
            '-serial', 'stdio', '-no-reboot',
            '-drive', 'file=sep_nvram,if=pflash,format=raw',
            '-drive', 'file=sep_ssc,if=pflash,format=raw']
    for name, nsid, nstype, device in [('root', 1, 1, 'nvme-ns'), ('firmware', 2, 2, 'nvme-ns'),
                                      ('syscfg', 3, 3, 'nvme-ns'), ('ctrl_bits', 4, 4, 'nvme-ns'),
                                      ('nvram', 5, 5, 'apple-nvram'), ('effaceable', 6, 6, 'nvme-ns'),
                                      ('panic_log', 7, 8, 'nvme-ns')]:
        args += ['-drive', 'file=%s,format=raw,if=none,id=%s' % (name, name),
                 '-device', ('%s,drive=%s,bus=nvme-bus.0,nsid=%s,nstype=%s,id=%s,'
                             'logical_block_size=4096,physical_block_size=4096' %
                             (device, name, nsid, nstype, name))]
    return args


class Machine:
    def __init__(self, args, stage, log_name, log_directory=None):
        self.console = deque(maxlen=12000)
        from .native_runtime import environment
        self.process = subprocess.Popen(args, cwd=str(stage), stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        env=environment(Path(args[0]).parent, stage, stage.parent))
        self.reader = threading.Thread(target=self._read, args=((log_directory or stage) / log_name,), daemon=True)
        self.reader.start()

    def _read(self, log_path):
        # Keep console output bounded, including firmware which emits long NUL runs.
        with log_path.open('wb') as log:
            line = bytearray()
            total = 0
            while data := self.process.stdout.read1(4096):
                data = data.replace(b'\0', b'')
                if total + len(data) > 32 * 1024 * 1024:
                    log.seek(0); log.truncate(); total = 0
                log.write(data); log.flush(); total += len(data)
                line += data
                while b'\n' in line:
                    raw, _, line = line.partition(b'\n')
                    self.console.append(raw.decode('utf-8', errors='replace').strip())
                if len(line) > 65536:
                    line = line[-65536:]

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=5)
        self.reader.join(timeout=3)
        if not self.reader.is_alive():
            self.process.stdout.close()


def seed_firmware(path, llb, ticket):
    # This pinned Pyre revision derives chosen/boot-manifest-hash from the
    # IMG4 at offset zero in the firmware namespace, not a -M ticket property.
    image = personalize(llb, ticket)
    if len(image) > path.stat().st_size:
        raise ValueError('Personalized LLB does not fit the firmware namespace')
    with path.open('r+b') as firmware:
        firmware.write(image)


def prepare(ipsw, rom, resources, stage, update):
    stage.mkdir()
    with zipfile.ZipFile(ipsw) as archive:
        manifest = plistlib.loads(archive.read('BuildManifest.plist'))
        identity = select_identity(manifest)
        for component, name in [('KernelCache', 'kernel'), ('DeviceTree', 'dtb'),
                                ('RestoreTrustCache', 'trustcache'), ('RestoreRamDisk', 'ramdisk')]:
            update('Extracting ' + component, -1.0)
            with archive.open(identity['Manifest'][component]['Info']['Path']) as source, (stage / name).open('wb') as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        template = (resources / 'ticket-template.plist').read_bytes()
        ticket = forge(template, identity)
        sep_ticket = forge(template, identity, sep=True)
        (stage / 'root_ticket.der').write_bytes(ticket)
        sep = archive.read(identity['Manifest']['SEP']['Info']['Path'])
        llb = archive.read(identity['Manifest']['LLB']['Info']['Path'])
        (stage / 'sep_fw').write_bytes(rebuild_sep(sep, sep_ticket, SEP_IV, SEP_KEY))
    shutil.copyfile(rom, stage / 'sep_rom')
    update('Preparing the guest filesystem patcher', -1.0)
    patch_ramdisk(stage / 'ramdisk', stage / 'ramdisk-patched',
                  resources / 'inferno_patcher', resources / 'inferno_fs_patcher', stage / 'sep_fw')
    for name, size in DISKS.items():
        with (stage / name).open('xb') as disk:
            disk.truncate(size)
    seed_firmware(stage / 'firmware', llb, ticket)
    props = 'kernel=kernel\ndtb=dtb\ntrustcache=trustcache\nsep_fw=sep_fw\nsep_rom=sep_rom\nroot=root\nroot_format=raw\nboot_mode=exit_recovery\n'
    (stage / 'vm.properties').write_text(props)
    return identity, ticket


def install(files_directory, native_directory, resources_directory, callback):
    base, native, resources = Path(str(files_directory)), Path(str(native_directory)), Path(str(resources_directory))
    update = callback.update
    cancelled = callback.isCancelled
    logs = base / 'ios-install-logs'; logs.mkdir(exist_ok=True)
    recovered = recover_installation(base)
    cleanup_staging(base)
    if recovered is not None:
        update('Recovered the prepared guest installation', 1.0)
        return
    checkpoint = find_restore_checkpoint(base)
    cache = base / 'ios-downloads'; cache.mkdir(exist_ok=True)
    minimum_space = (4 if checkpoint else 14) * 1024 ** 3
    if shutil.disk_usage(base).free < minimum_space:
        raise ValueError('At least %d GB of additional free storage is required' %
                         (4 if checkpoint else 14))
    for name, expected in ASSET_HASHES.items():
        if sha256(resources / name) != expected:
            raise ValueError('Bundled guest tool failed verification: ' + name)
    if checkpoint is None:
        ipsw = acquire(IPSW_URL, cache / '18A5351d.ipsw', IPSW_HASH,
                       lambda p: update('Downloading iOS 14.0 beta 5', p), cancelled)
        rom = acquire(ROM_URL, cache / 'AppleSEPROM-Cebu-B1', ROM_HASH,
                      lambda p: update('Downloading the emulated SEP ROM', p), cancelled)
    if cancelled():
        raise InterruptedError('Installation cancelled')
    stage = checkpoint or base / ('ios-staging-%d' % time.time_ns())
    try:
        if checkpoint is None:
            identity, ticket = prepare(ipsw, rom, resources, stage, update)
        else:
            update('Resuming CPU rendering patches from the completed restore', -1.0)
            patch_ramdisk(stage / 'ramdisk', stage / 'ramdisk-patched',
                          resources / 'inferno_patcher', resources / 'inferno_fs_patcher', stage / 'sep_fw')
    except BaseException:
        cleanup_staging(base)
        raise
    engine = native / 'libqemu-system-aarch64.so'
    usb, client_path = str(base / 'ios-usb.sock'), str(base / 'ios-mux.sock')
    bridge = Muxd(usb, client_path, str(cache / 'pair-records'))
    for method in (bridge.serve_usb, bridge.serve_clients):
        threading.Thread(target=method, daemon=True).start()
    if not bridge.usb_ready.wait(5) or not bridge.clients_ready.wait(5):
        bridge.stop()
        cleanup_staging(base)
        raise RuntimeError('Guest USB bridge could not start')
    machine = None
    finished = threading.Event()

    def check_cancel():
        while not finished.wait(0.25):
            if cancelled():
                bridge.stop()
                if machine:
                    machine.stop()
                return
    watcher = threading.Thread(target=check_cancel, daemon=True); watcher.start()
    try:
        if checkpoint is None:
            update('Booting the iOS restore environment with CPU emulation', -1.0)
            machine = Machine(command(engine, stage, resources, usb, 'ramdisk'), stage, 'restore-console.log', logs)
            deadline = time.monotonic() + 900
            while bridge.device is None:
                if cancelled():
                    raise InterruptedError('Installation cancelled')
                if machine.process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('Restore environment did not connect. See restore-console.log in Diagnostics.')
                time.sleep(0.25)
            update('Restoring the private iOS disk. CPU emulation can take several hours.', -1.0)
            connector = partial(mux_connect, address=client_path)
            client = RestoreClient(str(ipsw), identity, ticket, connect=connector,
                                   note=lambda message: update(str(message), -1.0),
                                   progress=lambda name, p: update(name, p), cancelled=cancelled)
            try:
                client.run()
            finally:
                client.close()
            try:
                machine.process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                pass
            machine.stop()
            record_restore_checkpoint(stage)
        if cancelled():
            raise InterruptedError('Installation cancelled')
        # A second recovery boot applies filesystem patches after restored has
        # released the volumes. This engine does not implement hold-reset.
        update('Applying CPU rendering patches to the restored guest', -1.0)
        machine = Machine(command(engine, stage, resources, usb, 'ramdisk-patched', patch_only=True),
                          stage, 'patch-console.log', logs)
        deadline = time.monotonic() + 3600
        while True:
            if cancelled():
                raise InterruptedError('Installation cancelled')
            lines = list(machine.console)
            if any('*** PATCHER: saved SEP preparation failed' in line or
                   '*** PATCHER: saved SEP cleanup failed' in line for line in lines):
                raise RuntimeError('Guest filesystem preparation failed. See patch-console.log.')
            if any('*** PATCHER: done, the machine can be reset now' in line for line in lines):
                machine.stop()
                record_installation(stage, list(machine.console))
                break
            if machine.process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('Guest filesystem patching did not finish. See patch-console.log.')
            time.sleep(0.5)
        if cancelled():
            raise InterruptedError('Installation cancelled')
        update('Verifying and saving the installed guest', -1.0)
        promote(stage, base / 'ios-current')
    finally:
        finished.set()
        if machine:
            machine.stop()
        bridge.stop()
        watcher.join(timeout=2)
        cleanup_staging(base)
