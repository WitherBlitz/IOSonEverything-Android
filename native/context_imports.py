"""Redirect just QEMU's two imported coroutine functions to app-local names.

Names have equal lengths, so no loadable segment, relocation, version, code or
section offset changes. Undefined symbols are resolved by name in dependencies;
they are not definitions in QEMU's exported-symbol hash table.
"""
import argparse
import hashlib
from pathlib import Path
import struct

RENAMES = {b'sigsetjmp': b'iossetjmp', b'siglongjmp': b'ioslongjmp'}


def rename_imports(original):
    if original[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', original, 18)[0] != 183:
        raise ValueError('Expected an ELF64 little-endian AArch64 engine')
    image = bytearray(original)
    sections_offset = struct.unpack_from('<Q', image, 40)[0]
    section_size, count = struct.unpack_from('<HH', image, 58)
    if section_size != 64 or not count or sections_offset + count * 64 > len(image):
        raise ValueError('Invalid section table')
    sections = [struct.unpack_from('<IIQQQQIIQQ', image, sections_offset + i * 64) for i in range(count)]
    changed = set()
    for section in sections:
        if section[1] != 11:  # SHT_DYNSYM
            continue
        if section[9] != 24 or section[6] >= count:
            raise ValueError('Invalid dynamic symbols')
        strings = sections[section[6]]
        if section[4] + section[5] > len(image) or strings[4] + strings[5] > len(image):
            raise ValueError('Truncated ELF')
        for position in range(section[4], section[4] + section[5], 24):
            name, info, visibility, index, value, size = struct.unpack_from('<IBBHQQ', image, position)
            start = strings[4] + name
            if name >= strings[5]:
                raise ValueError('Invalid symbol name')
            end = image.find(0, start, strings[4] + strings[5])
            if end < 0:
                raise ValueError('Unterminated symbol')
            symbol = bytes(image[start:end])
            if symbol in RENAMES:
                if index != 0 or symbol in changed:
                    raise ValueError('Expected one undefined import for each coroutine function')
                image[start:end] = RENAMES[symbol]
                changed.add(symbol)
    if changed != set(RENAMES):
        raise ValueError('Both original coroutine imports must be present')
    return bytes(image)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--sha256', required=True, help='Exact upstream input hash')
    args = parser.parse_args()
    original = args.input.read_bytes()
    if hashlib.sha256(original).hexdigest() != args.sha256:
        raise SystemExit('Input SHA256 mismatch; no output written')
    patched = rename_imports(original)
    args.output.write_bytes(patched)
    print(hashlib.sha256(patched).hexdigest(), args.output)
