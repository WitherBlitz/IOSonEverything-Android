# SPDX-License-Identifier: GPL-3.0-or-later
"""Resumable verified inputs and recoverable guest-install promotion."""
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
import urllib.request
import urllib.error


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def acquire(url, destination, expected_hash, progress=lambda value: None,
            cancelled=lambda: False, opener=None):
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and sha256(path) == expected_hash:
        progress(1.0)
        return path
    part = path.with_suffix(path.suffix + '.part')
    if cancelled():
        raise InterruptedError('Installation cancelled')
    if part.is_file() and sha256(part) == expected_hash:
        os.replace(part, path)
        progress(1.0)
        return path
    offset = part.stat().st_size if part.exists() else 0
    request = urllib.request.Request(url, headers={'User-Agent': 'IOSonEverything/0.1',
                                                  'Accept-Encoding': 'identity'})
    if offset:
        request.add_header('Range', 'bytes=%d-' % offset)
    open_request = opener or (lambda req: urllib.request.urlopen(req, timeout=60))
    if cancelled():
        raise InterruptedError('Installation cancelled')
    try:
        response = open_request(request)
    except urllib.error.HTTPError as error:
        if error.code != 416 or not offset:
            raise
        error.close()
        part.unlink()
        return acquire(url, path, expected_hash, progress, cancelled, opener)
    with response:
        if response.status == 206:
            if not response.headers.get('Content-Range', '').startswith('bytes %d-' % offset):
                raise ValueError('Server returned an incompatible resume range')
            mode = 'ab'
        elif response.status == 200:
            offset = 0
            mode = 'wb'
        else:
            raise ValueError('Unexpected download status: %s' % response.status)
        total = int(response.headers.get('Content-Length', 0)) + offset
        with part.open(mode) as target:
            while True:
                if cancelled():
                    raise InterruptedError('Installation cancelled')
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
                offset += len(chunk)
                progress(offset / total if total else -1.0)
            target.flush()
            os.fsync(target.fileno())
    if total and offset < total:
        raise ConnectionError('Download ended early; the partial file is retained for retry')
    if sha256(part) != expected_hash:
        part.unlink()
        raise ValueError('Input checksum mismatch; retry downloads a fresh copy')
    os.replace(part, path)
    progress(1.0)
    return path


def validate_receipt(directory):
    stage = Path(directory)
    receipt = stage / 'installation.json'
    try:
        if receipt.stat().st_size > 64 * 1024:
            raise ValueError('Oversized installation receipt')
        data = json.loads(receipt.read_text())
        if not isinstance(data, dict) or not isinstance(data.get('files'), dict) or not isinstance(data.get('static_sha256', {}), dict):
            raise ValueError('Invalid installation receipt structure')
        if data.get('profile') != 'iphone11-18A5351d-cpu-v1' or data.get('restored') is not True or data.get('patched') is not True:
            raise ValueError('Incomplete installation receipt')
        for name, size in data['files'].items():
            if type(size) is not int or size <= 0 or Path(name).name != name or not (stage / name).is_file() or (stage / name).stat().st_size != size:
                raise ValueError('Installation receipt file mismatch')
        required = {'root', 'kernel', 'dtb', 'trustcache', 'sep_rom', 'sep_fw', 'vm.properties',
                    'firmware', 'syscfg', 'ctrl_bits', 'nvram', 'effaceable', 'panic_log', 'sep_nvram', 'sep_ssc'}
        if not required <= data['files'].keys():
            raise ValueError('Incomplete installation receipt files')
        hashes = data.get('static_sha256', {})
        immutable = {'kernel', 'dtb', 'trustcache', 'sep_rom', 'sep_fw'}
        if set(hashes) != immutable:
            raise ValueError('Incomplete installation receipt hashes')
        for name, digest in hashes.items():
            if not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None or sha256(stage / name) != digest:
                raise ValueError('Installation receipt hash mismatch')
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError('Missing or invalid installation receipt') from error
    return data


def is_complete(directory):
    try:
        validate_receipt(directory)
        return True
    except (ValueError, OSError):
        return False


def validate_restore_checkpoint(directory):
    """A successful restore can resume patching, but cannot be opened as iOS yet."""
    stage = Path(directory)
    try:
        marker = stage / 'restore-complete.json'
        if marker.stat().st_size > 64 * 1024:
            raise ValueError('Oversized restore checkpoint')
        data = json.loads(marker.read_text())
        if (data.get('profile') != 'iphone11-18A5351d-cpu-v1' or
                data.get('restored') is not True or data.get('patched') is not False):
            raise ValueError('Incomplete restore checkpoint')
        required = {'root', 'kernel', 'dtb', 'trustcache', 'sep_rom', 'sep_fw', 'vm.properties',
                    'firmware', 'syscfg', 'ctrl_bits', 'nvram', 'effaceable', 'panic_log',
                    'sep_nvram', 'sep_ssc', 'ramdisk'}
        files, digests = data['files'], data['static_sha256']
        if not required <= files.keys() or set(digests) != {'kernel', 'dtb', 'trustcache', 'sep_rom', 'sep_fw', 'ramdisk'}:
            raise ValueError('Incomplete restore checkpoint files')
        for name, size in files.items():
            path = stage / name
            if (Path(name).name != name or type(size) is not int or size <= 0 or
                    not path.is_file() or path.stat().st_size != size):
                raise ValueError('Restore checkpoint file mismatch')
        for name, digest in digests.items():
            if sha256(stage / name) != digest:
                raise ValueError('Restore checkpoint hash mismatch')
        with (stage / 'root').open('rb') as root:
            header = root.read(8192)
        if header[512:520] != b'EFI PART' and header[4096:4104] != b'EFI PART':
            raise ValueError('Restore checkpoint has no GPT')
    except (OSError, AttributeError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError('Missing or invalid restore checkpoint') from error
    return data


def is_restore_checkpoint(directory):
    try:
        validate_restore_checkpoint(directory)
        return True
    except (ValueError, OSError):
        return False


def find_restore_checkpoint(base):
    base = Path(base).resolve()
    for candidate in sorted(base.glob('ios-staging-*'), reverse=True):
        if (candidate.is_symlink() or candidate.resolve().parent != base or
                re.fullmatch(r'ios-staging-[0-9]+', candidate.name) is None):
            continue
        if is_restore_checkpoint(candidate):
            return candidate
    return None


def cleanup_staging(base):
    """Reclaim only this installer's abandoned, incomplete private directories."""
    base = Path(base).resolve()
    for candidate in base.glob('ios-staging-*'):
        if (candidate.is_symlink() or candidate.resolve().parent != base or
                re.fullmatch(r'ios-staging-[0-9]+', candidate.name) is None):
            continue
        if candidate.is_dir() and not is_complete(candidate) and not is_restore_checkpoint(candidate):
            shutil.rmtree(candidate)


def recover_installation(base):
    """Receipts and retained directories form the durable promotion journal."""
    base = Path(base)
    current = base / 'ios-current'
    if is_complete(current):
        return current
    previous = base / 'ios-current.previous'
    candidates = [previous] + sorted(base.glob('ios-staging-*'), reverse=True)
    for candidate in candidates:
        if (candidate.is_symlink() or candidate.resolve().parent != base.resolve() or
                (candidate != previous and re.fullmatch(r'ios-staging-[0-9]+', candidate.name) is None)):
            continue
        if is_complete(candidate):
            if current.exists():
                os.replace(current, base / ('ios-damaged-%d' % time.time_ns()))
            os.replace(candidate, current)
            return current
    return None


def promote(staging, current):
    stage, current = Path(staging), Path(current)
    validate_receipt(stage)
    backup = current.with_name(current.name + '.previous')
    if backup.exists():
        raise ValueError('Previous installation backup requires recovery')
    had_previous = current.exists()
    if had_previous:
        os.replace(current, backup)
    try:
        os.replace(stage, current)
    except BaseException:
        if had_previous:
            os.replace(backup, current)
        raise
    # Retain the previous valid installation until explicitly removed by the user.
    return current
