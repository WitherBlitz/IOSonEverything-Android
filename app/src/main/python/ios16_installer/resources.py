"""Validate caller-supplied, source-built resources; never search private/ready."""
from pathlib import Path
import re
import struct
import plistlib
from .safety import checked_path, digest, Hooks, safe_relative
from .persistence import validate_persistence

PROFILE = 'ios16.5-20F66-virt-cpu-v1'
USERLAND_COMMIT = '05afc43591d81ee2fe3cda943b728b39c3bda257'
KERNEL_COMMIT = '1603ed003665a07753c260b76929c4a3a1796681'
PATCHES = {'1100', '1101', '1201', '1202'}
CPU_INJECTIONS = {'/redwood/lib/libredwood.dylib': ['backboardd','containermanagerd','containermanagerd_system'],
                  '/redwood/lib/libredwood-sb.dylib': ['SpringBoard'],
                  '/redwood/lib/libredwood-media.dylib': ['mediaserverd']}
AUDIO_CONFIG_NAME = 'RedwoodAudio.Info.plist'
AUDIO_CONFIG_PATH = 'lib/RedwoodAudio.driver/Info.plist'
AUDIO_EXECUTABLE_PATH = 'lib/RedwoodAudio.driver/RedwoodAudio'
AUDIO_CONFIG_SHA256 = '8737f502b722742a6a37bce8c512220fabc18add88717f4eb8fae5524a08d6fd'

def validate_owned_audio_config(entry,path):
    source=entry.get('source',{})
    if (entry.get('kind')!='source-owned-config' or entry.get('bytes')!=1048 or
        type(entry.get('mode')) is not int or entry['mode']!=0o644 or
        entry.get('sha256')!=AUDIO_CONFIG_SHA256 or
        source.get('commit')!=USERLAND_COMMIT or source.get('license')!='MIT' or
        source.get('repository')!='https://github.com/dylanneve1/hackios-xnu-userland' or
        source.get('path')!='userland/src/audio_plugin.plist'):
        raise ValueError('Owned audio configuration provenance/mode differs')
    path=Path(path)
    if path.is_symlink() or path.stat().st_size!=1048 or digest(path)!=AUDIO_CONFIG_SHA256:
        raise ValueError('Owned audio configuration is not the exact pinned source blob')
    values=plistlib.loads(path.read_bytes())
    if (values.get('CFBundleIdentifier')!='com.redwood.audio' or
        values.get('CFBundleExecutable')!='RedwoodAudio' or values.get('CFBundlePackageType')!='BNDL'):
        raise ValueError('Owned audio bundle identity differs')
    return True

def audit_kernel(path):
    """Recheck required implementation evidence in the actual input, no external nm."""
    if path.stat().st_size > 64 * 1024**2: raise ValueError('Kernel audit size limit exceeded')
    data = path.read_bytes()
    if len(data) < 32: raise ValueError('Truncated kernel')
    magic, cpu, _, kind, commands, command_bytes, _, _ = struct.unpack_from('<8I', data)
    if magic != 0xfeedfacf or cpu != 0x100000c or kind != 2 or 32 + command_bytes > len(data):
        raise ValueError('Invalid executable kernel Mach-O')
    at = 32; symbols = set(); segments = 0
    for _ in range(commands):
        if at + 8 > 32 + command_bytes: raise ValueError('Truncated Mach-O command')
        command, size = struct.unpack_from('<II', data, at)
        if size < 8 or size % 8 or at + size > 32 + command_bytes: raise ValueError('Invalid Mach-O command')
        if command == 0x19:
            if size < 72: raise ValueError('Truncated segment')
            _, _, virtual_size, offset, file_size = struct.unpack_from('<16s4Q', data, at + 8)
            if file_size > virtual_size or offset + file_size > len(data): raise ValueError('Invalid kernel segment')
            segments += 1
        if command == 2:
            if size < 24: raise ValueError('Truncated symbol command')
            offset, count, strings, string_bytes = struct.unpack_from('<4I', data, at + 8)
            if offset + count * 16 > len(data) or strings + string_bytes > len(data): raise ValueError('Invalid symbol table')
            for index in range(count):
                name = struct.unpack_from('<I', data, offset + index * 16)[0]
                if name >= string_bytes: raise ValueError('Invalid kernel symbol name')
                end = data.find(b'\0', strings + name, strings + string_bytes)
                if end < 0: raise ValueError('Unterminated kernel symbol')
                symbols.add(data[strings + name:end])
        at += size
    required = [b'_redwood_pci_init', b'_vio_pci', b'_vio_find', b'_redwood_virtio_blk_rootdev',
                b'_redwood_virtio_blk_alias', b'_redwood_vgpu_display', b'_redwood_vgpu_flush',
                b'_redwood_virtio_input_init']
    if at != 32 + command_bytes or not segments or not set(required) <= symbols:
        raise ValueError('Required virtio PCI/md0/display/input implementation symbols absent')
    if not all(text in data for text in (b'BSD root: md0 =', b'multi-touch', b'virtio-gpu: scanout 0 is')):
        raise ValueError('Required kernel implementation messages absent')
    return {'symbols': [item.decode() for item in required], 'segments': segments,
            'evidence': 'bounded Mach-O symbol/segment and implementation-message audit; source provenance separately supplied'}

def validate_resources(manifest, asset_root, native_root, hooks=None):
    hooks = hooks or Hooks()
    if manifest.get('schema_version') != 1 or manifest.get('profile') != PROFILE:
        raise ValueError('Resource manifest profile/schema differs')
    entries = manifest.get('resources', {})
    if not {'Image', 'kernel', 'stage0', 'init', 'child', '7zz', 'unzbm'} <= set(entries):
        raise ValueError('Required source-built resources are absent')
    result = {}
    for name, entry in entries.items():
        safe_relative(name)
        if '/' in name: raise ValueError('Resource names must be single components')
        tool = name in ('7zz', 'unzbm')
        config = name == AUDIO_CONFIG_NAME
        expected_kind='android-native-tool' if tool else 'source-owned-config' if config else 'source-built-guest'
        if entry.get('kind') != expected_kind:
            raise ValueError('Unexpected resource kind')
        provenance = entry.get('source', {})
        if not provenance.get('license') or not re.fullmatch('[0-9a-f]{40}', provenance.get('commit', '')):
            raise ValueError('Full source commit and license required')
        if not provenance.get('repository', '').startswith('https://github.com/'):
            raise ValueError('Open-source repository URL required')
        path = checked_path(native_root if tool else asset_root, entry['path'])
        sha = entry.get('sha256', '')
        if not re.fullmatch('[0-9a-f]{64}', sha) or type(entry.get('bytes')) is not int or entry['bytes'] <= 0:
            raise ValueError('Resource size/hash missing')
        if not path.is_file() or path.stat().st_size != entry['bytes'] or digest(path, 'sha256', hooks) != sha:
            raise ValueError('Source-built resource verification failed: ' + name)
        with path.open('rb') as stream: head = stream.read(64)
        if config:
            validate_owned_audio_config(entry,path)
        elif tool:
            if len(head) < 64 or head[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', head, 18)[0] != 183:
                raise ValueError('Native tool must be Android AArch64 ELF')
        elif name == 'Image':
            if head[56:60] != b'ARM\x64': raise ValueError('Boot shim lacks arm64 Linux Image header')
        else:
            if len(head) < 32 or head[:4] != b'\xcf\xfa\xed\xfe' or struct.unpack_from('<I', head, 4)[0] != 0x100000c:
                raise ValueError('Guest resource must be arm64 Mach-O')
        result[name] = path
    audit = manifest.get('kernel_audit', {})
    if (audit.get('kernel_sha256') != entries['kernel']['sha256'] or
        audit.get('source_commit') != KERNEL_COMMIT or
        set(audit.get('verified_patches', [])) != PATCHES or
        audit.get('verification') != 'source-and-symbol-audit'):
        raise ValueError('Kernel patch audit is absent or not bound to this kernel')
    if entries['kernel']['source']['commit'] != KERNEL_COMMIT:
        raise ValueError('Kernel source pin differs')
    for name in ('stage0', 'init', 'child'):
        if entries[name]['source']['commit'] != USERLAND_COMMIT:
            raise ValueError('Userland source pin differs')
    for guest_path, processes in CPU_INJECTIONS.items():
        name = manifest.get('root_files', {}).get(guest_path[len('/redwood/'):])
        if name not in entries or entries[name]['source']['commit'] != USERLAND_COMMIT:
            raise ValueError('Pinned CPU userland glue not staged: ' + guest_path)
        if not set(processes) <= set(manifest.get('injections', {}).get(guest_path, [])):
            raise ValueError('Required CPU injection is absent: ' + guest_path)
    root_files=manifest.get('root_files',{})
    if AUDIO_CONFIG_NAME in entries or AUDIO_EXECUTABLE_PATH in root_files:
        executable=root_files.get(AUDIO_EXECUTABLE_PATH)
        if (root_files.get(AUDIO_CONFIG_PATH)!=AUDIO_CONFIG_NAME or executable not in entries or
            entries[executable].get('kind')!='source-built-guest'):
            raise ValueError('Owned audio bundle configuration/executable mapping is incomplete')
    validate_persistence(manifest)
    audit_kernel(result['kernel'])
    return result
