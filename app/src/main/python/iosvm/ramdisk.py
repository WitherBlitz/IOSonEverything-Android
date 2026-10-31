# SPDX-License-Identifier: GPL-3.0-or-later
"""In-place HFSX file replacement, ported from Inferno-iOS RestoreRamdisk.swift.

Only private staging copies of the selected restore ramdisk are modified.
No catalog insertion, arbitrary filesystem writing or host mount is required.
"""
import os
import plistlib
import shutil
import struct

from .firmware import read_element

DAEMON = '/usr/standalone/firmware/nfrestore/firmware/jcop-prod/JCOP-01.30-006-P.bin'
PATCHER = '/usr/standalone/firmware/nfrestore/firmware/jcop-prod/JCOP-11.04-012.2-P.bin'
JOB = '/System/Library/LaunchDaemons/com.apple.syslogd.plist'
RESTORED_JOB = '/System/Library/LaunchDaemons/com.apple.restored_external.plist'
# This stock tool is unused in the post-restore boot. Its catalog entry carries
# the prepared firmware so seputil can load SEP before the encrypted Data mount.
SEP_PAYLOAD = '/usr/bin/peppytool'


def be16(data, offset):
    return struct.unpack_from('>H', data, offset)[0]


def be32(data, offset):
    return struct.unpack_from('>I', data, offset)[0]


def fork(data, offset):
    size = struct.unpack_from('>Q', data, offset)[0]
    extents = [struct.unpack_from('>II', data, offset + 16 + i * 8) for i in range(8)]
    return size, [(start, count) for start, count in extents if count]


class Volume:
    def __init__(self, source, base):
        self.source, self.base = source, base
        source.seek(0, 2)
        self.limit = source.tell()
        header = self.read(base + 1024, 512)
        if header[:2] not in (b'H+', b'HX'):
            raise ValueError('Ramdisk is not raw HFSX')
        self.block_size = be32(header, 40)
        self.blocks = be32(header, 44)
        if not 512 <= self.block_size <= 65536 or self.blocks * self.block_size + base > self.limit:
            raise ValueError('Invalid HFS allocation geometry')
        self.allocation, self.catalog = fork(header, 112), fork(header, 272)
        node = self.read(self.fork_offset(self.catalog, 0), 512)
        self.node_size, self.first_leaf = be16(node, 32), be32(node, 24)
        if not 512 <= self.node_size <= 32768:
            raise ValueError('Invalid HFS catalog node size')

    def read(self, offset, count):
        if offset < self.base or count < 0 or offset + count > self.limit:
            raise ValueError('HFS read exceeds ramdisk')
        self.source.seek(offset)
        result = self.source.read(count)
        if len(result) != count:
            raise ValueError('Truncated HFS data')
        return result

    def write(self, offset, data):
        if offset < self.base or offset + len(data) > self.limit:
            raise ValueError('HFS write exceeds ramdisk')
        self.source.seek(offset)
        self.source.write(data)

    def fork_offset(self, entry, offset):
        for start, count in entry[1]:
            size = count * self.block_size
            if offset < size:
                return self.base + start * self.block_size + offset
            offset -= size
        raise ValueError('HFS extent overflow is unsupported')

    def fork_read(self, entry, count):
        result = bytearray()
        for start, blocks in entry[1]:
            size = min(count - len(result), blocks * self.block_size)
            result += self.read(self.base + start * self.block_size, size)
            if len(result) == count:
                return result
        raise ValueError('Truncated HFS fork')

    def fork_write(self, entry, data):
        written = 0
        for start, blocks in entry[1]:
            size = min(len(data) - written, blocks * self.block_size)
            self.write(self.base + start * self.block_size, data[written:written + size])
            written += size
            if written == len(data):
                return
        raise ValueError('HFS fork has insufficient allocation')

    def find(self, path):
        parent, result = 2, None
        for name in filter(None, path.split('/')):
            node_index, seen, result = self.first_leaf, set(), None
            while node_index:
                if node_index in seen:
                    raise ValueError('HFS catalog leaf cycle')
                seen.add(node_index)
                node_offset = self.fork_offset(self.catalog, node_index * self.node_size)
                node = self.read(node_offset, self.node_size)
                records = be16(node, 10)
                if records > self.node_size // 2 - 8:
                    raise ValueError('Invalid catalog record count')
                for index in range(records):
                    offset = be16(node, self.node_size - 2 * (index + 1))
                    key_len = be16(node, offset)
                    if be32(node, offset + 2) != parent:
                        continue
                    name_len = be16(node, offset + 6)
                    if node[offset + 8:offset + 8 + name_len * 2] != name.encode('utf-16-be'):
                        continue
                    at = (offset + 2 + key_len + 1) & ~1
                    kind = be16(node, at)
                    if kind in (1, 2):
                        result = (kind, be32(node, at + 8), node_offset + at,
                                  fork(node, at + 88) if kind == 2 else (0, []))
                        break
                if result:
                    break
                node_index = be32(node, 0)
            if result is None:
                raise ValueError('Missing ramdisk path: ' + path)
            parent = result[1]
        return result

    def allocate(self, blocks):
        bitmap = self.fork_read(self.allocation, (self.blocks + 7) // 8)
        run = start = 0
        for index in range(self.blocks):
            if bitmap[index >> 3] & (0x80 >> (index & 7)):
                run = 0
                continue
            if not run:
                start = index
            run += 1
            if run == blocks:
                free = be32(self.read(self.base + 1024 + 48, 4), 0)
                if free < blocks:
                    raise ValueError('Invalid HFS free block count')
                for taken in range(start, start + blocks):
                    bitmap[taken >> 3] |= 0x80 >> (taken & 7)
                self.fork_write(self.allocation, bitmap)
                self.write(self.base + 1024 + 48, struct.pack('>I', free - blocks))
                return start
        raise ValueError('Ramdisk has no free allocation run')

    def replace(self, path, data, mode):
        kind, _, record, entry = self.find(path)
        if kind != 2:
            raise ValueError('Cannot replace a ramdisk folder')
        extents = entry[1]
        if sum(n for _, n in extents) * self.block_size < len(data):
            needed = (len(data) + self.block_size - 1) // self.block_size
            extents = [(self.allocate(needed), needed)]
            self.write(record + 100, struct.pack('>I', needed))
            self.write(record + 104, struct.pack('>II', extents[0][0], needed) + bytes(56))
        self.fork_write((len(data), extents), data)
        self.write(record + 88, struct.pack('>Q', len(data)))
        self.write(record + 42, struct.pack('>H', mode | 0o100000))
        self.write(record + 32, bytes(8))
        self.write(record + 41, b'\0')


def payload_offset(source):
    source.seek(0)
    head = source.read(256)
    # Header walk only: the large OCTET STRING extends beyond these 256 bytes.
    def header(at):
        tag, length = head[at:at + 2]
        at += 2
        if length & 128:
            count = length & 127
            if not 0 < count <= 4:
                raise ValueError('Invalid ramdisk DER length')
            length = int.from_bytes(head[at:at + count], 'big'); at += count
        return tag, at, length
    tag, at, _ = header(0)
    if tag != 0x30:
        raise ValueError('Expected IM4P ramdisk')
    for expected in (b'IM4P', None, None):
        tag, at, length = header(at)
        if tag != 0x16 or (expected is not None and head[at:at + length] != expected):
            raise ValueError('Invalid ramdisk IM4P fields')
        at += length
    tag, at, _ = header(at)
    if tag != 4:
        raise ValueError('Expected ramdisk OCTET STRING')
    return at


def patch_ramdisk(stock, destination, daemon, patcher, sep_firmware):
    shutil.copyfile(stock, destination)
    job = plistlib.dumps({'Label': 'com.inferno.patcher', 'ProgramArguments': [DAEMON],
                          'RunAtLoad': True, 'StandardOutPath': '/dev/console', 'StandardErrorPath': '/dev/console'})
    with open(destination, 'r+b') as source:
        volume = Volume(source, payload_offset(source))
        volume.replace(JOB, job, 0o644)
        # This ramdisk is used only after a successful restore. A stock restored
        # daemon would reset the machine after its 120-second host wait. The
        # adapted patcher serializes xART mount, gigalocker initialization, SEP
        # load and ping before it mounts Data, then closes xART after Data unmount.
        disabled = plistlib.dumps({'Label': 'com.apple.restored_external', 'Disabled': True,
                                   'ProgramArguments': ['/usr/local/bin/restored_external']})
        volume.replace(RESTORED_JOB, disabled, 0o644)
        with open(sep_firmware, 'rb') as firmware:
            volume.replace(SEP_PAYLOAD, firmware.read(), 0o644)
        for path, tool in [(DAEMON, daemon), (PATCHER, patcher)]:
            with open(tool, 'rb') as binary:
                data = binary.read()
            if data[:4] != b'\xcf\xfa\xed\xfe':
                raise ValueError('Guest patcher is not ARM64 Mach-O')
            volume.replace(path, data, 0o755)
        source.flush()
        os.fsync(source.fileno())
