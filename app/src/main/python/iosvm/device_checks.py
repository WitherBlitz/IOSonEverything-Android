# SPDX-License-Identifier: GPL-3.0-or-later
"""Small real-device checks invoked only by the separate instrumentation APK."""
import json
from pathlib import Path
import socket
import subprocess
import shutil
import threading
import time

from .firmware import decrypt_sep
from .vendor.tcpusb import listen
from .native_runtime import environment


def installer_tools_smoke(files, native):
    """Run the separately staged synthetic tool fixtures from this ordinary app UID."""
    import runpy
    import sys
    base = Path(str(files)) / 'ios16-tools-smoke'
    lib = Path(str(native))
    previous = sys.argv
    try:
        sys.argv = [str(base / 'smoke-app-uid.py'), '--sevenzip', str(lib / 'libios16-7zz.so'),
                    '--unzbm', str(lib / 'libios16-unzbm.so'), '--fixtures', str(base / 'fixtures'),
                    '--work', str(base / 'results'), '--require-app-uid']
        runpy.run_path(sys.argv[0], run_name='__main__')
    finally:
        sys.argv = previous
    reports = list((base / 'results').glob('ios16-tools-smoke-*/result.json'))
    if not reports:
        raise RuntimeError('Installer tool smoke did not finish')
    return max(reports, key=lambda p: p.stat().st_mtime).read_text()


def installer_audit(files, native, url, digest):
    """Exercise real acquisition with disposable inputs and preserve a usable guest."""
    from .acquisition import acquire, sha256, validate_receipt
    from .installer import install
    from types import SimpleNamespace
    import hashlib
    base = Path(str(files))
    current = base / 'ios-current'
    validate_receipt(current)
    before_receipt = (current / 'installation.json').read_bytes()
    before_disks = {name: (p.stat().st_ino, p.stat().st_size, p.stat().st_mtime_ns)
                    for name in ('root', 'firmware', 'syscfg', 'ctrl_bits', 'nvram',
                                 'effaceable', 'panic_log', 'sep_nvram', 'sep_ssc')
                    for p in [current / name]}
    scratch = base / ('installer-audit-%d' % time.time_ns())
    scratch.mkdir()
    try:
        target = scratch / 'download'
        try:
            acquire(str(url) + '/input', target, str(digest))
        except ConnectionError:
            pass
        partial = target.with_suffix('.part')
        if not partial.is_file() or partial.stat().st_size != 8192 or target.exists():
            raise RuntimeError('Short response did not retain the unpromoted 8192-byte prefix')
        acquire(str(url) + '/input', target, str(digest))
        if sha256(target) != str(digest) or partial.exists():
            raise RuntimeError('Resumed input did not verify and promote')
        old = target.read_bytes()
        try:
            acquire(str(url) + '/corrupt', target, '0' * 64)
        except ValueError:
            pass
        else:
            raise RuntimeError('Corrupt transfer was accepted')
        if target.read_bytes() != old:
            raise RuntimeError('Corrupt transfer replaced the existing input')
        messages = []
        # A verified current guest returns before acquisition/preparation. Also
        # request cancellation so an unexpected recovery miss cannot start a restore.
        install(base, Path(str(native)), base / 'installer-resources',
                SimpleNamespace(update=lambda text, _: messages.append(text), isCancelled=lambda: True))
        if messages != ['Recovered the prepared guest installation']:
            raise RuntimeError('Existing guest was not reused')
        after_disks = {name: (p.stat().st_ino, p.stat().st_size, p.stat().st_mtime_ns)
                       for name in before_disks for p in [current / name]}
        if (current / 'installation.json').read_bytes() != before_receipt or before_disks != after_disks:
            raise RuntimeError('Existing guest changed during recovery')
        validate_receipt(current)
        report = {'short_response_retained_bytes': 8192, 'resumed_sha256': str(digest),
                  'corrupt_transfer_rejected': True, 'previous_input_preserved': True,
                  'existing_guest_reused': True, 'guest_disk_metadata_unchanged': True,
                  'receipt_sha256': hashlib.sha256(before_receipt).hexdigest(),
                  'immutable_boot_hashes_verified': 5,
                  'ios_boot': 'Previously verified separately; no guest launched by this check'}
        (base / 'installer-audit-report.json').write_text(json.dumps(report, indent=2))
        return json.dumps(report)
    finally:
        shutil.rmtree(scratch)


def run(files, native):
    base = Path(str(files))
    plain = decrypt_sep(bytes.fromhex('f58c4c04d6e5f1ba779eabfb5f7bfbd6'),
                        bytes.fromhex('000102030405060708090a0b0c0d0e0f'),
                        bytes.fromhex('603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4'))
    if plain.hex() != '6bc1bee22e409f96e93d7e117393172a':
        raise RuntimeError('Android AES-256-CBC check failed')
    path = str(base / 'smoke-usb.sock')
    try:
        with listen(path) as server, socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(path)
            with server.accept()[0] as accepted:
                client.sendall(b'USB')
                if accepted.recv(3) != b'USB':
                    raise RuntimeError('Private USB socket check failed')
    finally:
        Path(path).unlink(missing_ok=True)
    engine = str(Path(str(native)) / 'libqemu-system-aarch64.so')
    version = subprocess.run([engine, '--version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=environment(str(native), base, base), timeout=10).stdout.decode()
    report = {'aes256_cbc': 'passed', 'private_unix_socket': 'passed', 'native_engine': version.strip(),
              'ios_boot': 'not established by this check'}
    (base / 'device-smoke.json').write_text(json.dumps(report, indent=2))
    return json.dumps(report)


def patch_boot_probe(files, native):
    """Boot only a disposable blank guest to verify patch-mode storage/lifetime."""
    from .installer import prepare, command, Machine
    from .vendor.muxd import Muxd
    base, native = Path(str(files)), Path(str(native))
    stage = base / ('ios-probe-%d' % time.time_ns())
    resources, cache = base / 'installer-resources', base / 'ios-downloads'
    prepare(cache / '18A5351d.ipsw', cache / 'AppleSEPROM-Cebu-B1', resources, stage,
            lambda *_: None)
    usb, mux = str(stage / 'usb'), str(stage / 'mux')
    bridge = Muxd(usb, mux, str(cache / 'pair-records'))
    machine = None
    try:
        for method in (bridge.serve_usb, bridge.serve_clients):
            threading.Thread(target=method, daemon=True).start()
        if not bridge.usb_ready.wait(5) or not bridge.clients_ready.wait(5):
            raise RuntimeError('Probe USB bridge did not start')
        machine = Machine(command(native / 'libqemu-system-aarch64.so', stage, resources,
                                  usb, 'ramdisk-patched', patch_only=True),
                          stage, 'patch-boot-probe.log', base)
        started = time.monotonic()
        while time.monotonic() - started < 145:
            text = '\n'.join(machine.console)
            if 'FW update not complete, create dummy block device' in text:
                raise RuntimeError('Patch-mode boot still exposes dummy NAND storage')
            if machine.process.poll() is not None:
                raise RuntimeError('Patch-mode boot exited before the timeout check')
            time.sleep(0.5)
        if '*** PATCHER: waiting for the restore to finish' not in text:
            raise RuntimeError('Patch daemon did not start on the disposable blank guest')
        if 'waiting for host to trigger start of restore' in text:
            raise RuntimeError('Idle restore daemon is still enabled in patch-mode boot')
        report = {'patch_ramdisk_alive_after_120_seconds': True,
                  'dummy_nand_device': False, 'idle_restored_daemon': False,
                  'ios_boot': 'not established; disposable blank guest only'}
        (base / 'patch-boot-probe.json').write_text(json.dumps(report, indent=2))
        return json.dumps(report)
    finally:
        if machine:
            machine.stop()
        bridge.stop()
        shutil.rmtree(stage)
