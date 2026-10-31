"""Adapt the pinned GPL guest daemon without an Apple SDK or layout changes.

LLVM inspection of the exact input established the cstring and execv call below.
The first change excludes all dotted cache sidecars for this single-cache iOS 14
profile. The second logs child exec paths using Darwin's stack variadic ABI.
The third sequences saved xART/SEP preparation and cleanup for cold recovery.
Only the existing ad-hoc CodeDirectory page hashes are regenerated; there is no
certificate, signing key, CMS signature or system trust-policy modification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

ORIGINAL_SHA256 = '8fbf7748dc923f78cf0752251baee2626b9c891cbe5e4a62d53592f92f8091cf'
SEP_CODE_SHA256 = '4f02b038929aee4c540621aa7a08ca7aeb6482bcc0b795ee67c70a11ae9ce138'


def code_directory(image):
    if image[:4] != b'\xcf\xfa\xed\xfe':
        raise ValueError('Expected thin 64-bit Mach-O')
    count, commands_size = struct.unpack_from('<II', image, 16)
    offset, signature = 32, None
    if count > 128 or 32 + commands_size > len(image):
        raise ValueError('Invalid Mach-O load commands')
    for _ in range(count):
        command, size = struct.unpack_from('<II', image, offset)
        if size < 8 or offset + size > 32 + commands_size:
            raise ValueError('Invalid Mach-O command size')
        if command == 0x1d:
            if signature is not None:
                raise ValueError('Duplicate code signature')
            signature = struct.unpack_from('<II', image, offset + 8)
        offset += size
    if signature is None:
        raise ValueError('No ad-hoc code signature')
    start, size = signature
    if start + size > len(image):
        raise ValueError('Invalid code signature range')
    magic, length, count = struct.unpack_from('>III', image, start)
    if magic != 0xfade0cc0 or length > size or count > 16:
        raise ValueError('Invalid code-signature superblob')
    directories = []
    for index in range(count):
        kind, relative = struct.unpack_from('>II', image, start + 12 + 8 * index)
        blob = start + relative
        if blob + 8 > start + length:
            raise ValueError('Invalid signature blob')
        blob_magic, blob_length = struct.unpack_from('>II', image, blob)
        if blob_length < 8 or blob + blob_length > start + length:
            raise ValueError('Invalid signature blob size')
        if kind == 0:
            directories.append(blob)
        elif kind == 0x10000 and (blob_magic != 0xfade0b01 or blob_length != 8):
            raise ValueError('Certificate-signed input is unsupported')
    if len(directories) != 1:
        raise ValueError('Expected one CodeDirectory')
    cd = directories[0]
    magic, length, version, flags, hash_offset, _, specials, slots, limit = struct.unpack_from('>9I', image, cd)
    hash_size, hash_type, _, page_shift = struct.unpack_from('4B', image, cd + 36)
    if (magic != 0xfade0c02 or flags != 2 or hash_type != 2 or hash_size != 32 or
            page_shift != 12 or limit > start or slots != (limit + 4095) // 4096 or
            hash_offset < specials * hash_size or hash_offset + slots * hash_size > length):
        raise ValueError('Unsupported ad-hoc CodeDirectory')
    return cd + hash_offset, slots, limit


def verify_code_hashes(image):
    hashes, slots, limit = code_directory(image)
    for index in range(slots):
        digest = hashlib.sha256(image[index * 4096:min((index + 1) * 4096, limit)]).digest()
        if image[hashes + index * 32:hashes + (index + 1) * 32] != digest:
            raise ValueError('Ad-hoc code page hash mismatch')


def branch(source, target, link=False):
    delta = target - source
    if delta % 4 or not -(1 << 27) <= delta < (1 << 27):
        raise ValueError('Branch out of range')
    return (0x94000000 if link else 0x14000000) | ((delta >> 2) & 0x3ffffff)


def adr(register, source, target):
    delta = target - source
    if not -(1 << 20) <= delta < (1 << 20):
        raise ValueError('ADR out of range')
    return 0x10000000 | ((delta & 3) << 29) | (((delta >> 2) & 0x7ffff) << 5) | register


def adapt(original):
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA256:
        raise ValueError('Original guest daemon SHA-256 mismatch')
    verify_code_hashes(original)
    if (original[0x495f:0x4964] != b'.map\0' or any(original[0x1000:0x1900]) or
            struct.unpack_from('<I', original, 0x45cc)[0] != branch(0x45cc, 0x46b0, True) or
            struct.unpack_from('<I', original, 0x40cc)[0] != branch(0x40cc, 0x46c0, True) or
            struct.unpack_from('<I', original, 0x458c)[0] != branch(0x458c, 0x46d0, True) or
            struct.unpack_from('<I', original, 0x45ac)[0] != branch(0x45ac, 0x4720, True)):
        raise ValueError('Pinned guest daemon layout mismatch')
    image = bytearray(original)
    image[0x495f:0x4964] = b'.\0\0\0\0'
    # Compiled/checked against native/guest-exec-trace.S. __TEXT is RX from
    # file offset 0 to 0x8000; unused header padding starts after load commands.
    words = [0xd100c3ff, 0xa90207e0, 0xf90003e0, 0xf9400422, 0xf90007e2,
             0xd503201f, 0xd503201f, 0xaa1f03e0, 0xd503201f, 0xa94207e0,
             0x9100c3ff, 0xd503201f, 0xd503201f]
    cave, message = 0x1000, 0x1080
    words[5] = adr(0, cave + 5 * 4, message)
    words[6] = branch(cave + 6 * 4, 0x4710, True)  # existing printf stub
    words[8] = branch(cave + 8 * 4, 0x46c0, True)  # existing fflush stub
    words[11] = adr(30, cave + 11 * 4, 0x45d0)
    words[12] = branch(cave + 12 * 4, 0x1700)  # checked unmount or original execv
    code = struct.pack('<13I', *words)
    image[cave:cave + len(code)] = code
    text = b'*** PATCHER: executing %s %s\n\0'
    image[message:message + len(text)] = text
    struct.pack_into('<I', image, 0x45cc, branch(0x45cc, cave))
    sep_code = Path(__file__).with_name('guest-sep-prepare.bin').read_bytes()
    if len(sep_code) != 0x700 or hashlib.sha256(sep_code).hexdigest() != SEP_CODE_SHA256:
        raise ValueError('SEP preparation code SHA-256 mismatch; rebuild from the retained assembly')
    image[0x1200:0x1900] = sep_code
    struct.pack_into('<I', image, 0x40cc, branch(0x40cc, 0x1200, True))
    struct.pack_into('<I', image, 0x458c, branch(0x458c, 0x12e0))
    hashes, slots, limit = code_directory(image)
    for index in range(slots):
        image[hashes + index * 32:hashes + (index + 1) * 32] = hashlib.sha256(
            image[index * 4096:min((index + 1) * 4096, limit)]).digest()
    verify_code_hashes(image)
    return bytes(image)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = adapt(args.original.read_bytes())
    args.output.write_bytes(result)
    print(json.dumps({'bytes': len(result), 'sha256': hashlib.sha256(result).hexdigest()}))
