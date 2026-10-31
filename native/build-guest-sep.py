"""Reproduce the SDK-free AArch64 routine used by adapt_guest_daemon.py."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile

from adapt_guest_daemon import SEP_CODE_SHA256


def build(llvm_directory):
    root = Path(__file__).resolve().parent
    suffix = '.exe' if (llvm_directory / 'clang.exe').exists() else ''
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        obj, raw = temporary / 'sep.o', temporary / 'sep.bin'
        subprocess.run([str(llvm_directory / ('clang' + suffix)),
                        '--target=aarch64-linux-android34', '-c',
                        str(root / 'guest-sep-prepare.S'), '-o', str(obj)], check=True)
        relocations = subprocess.check_output([str(llvm_directory / ('llvm-readelf' + suffix)),
                                               '-r', str(obj)], text=True)
        if 'There are no relocations in this file.' not in relocations:
            raise ValueError('Injected code must have no relocations')
        subprocess.run([str(llvm_directory / ('llvm-objcopy' + suffix)), '-O', 'binary',
                        '--only-section=.text', str(obj), str(raw)], check=True)
        code = raw.read_bytes()[0x1200:0x1900]
        if hashlib.sha256(code).hexdigest() != SEP_CODE_SHA256:
            raise ValueError('Assembled code differs from the reviewed routine')
        (root / 'guest-sep-prepare.bin').write_bytes(code)
        print('Verified %d bytes: %s' % (len(code), SEP_CODE_SHA256))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('llvm_directory', type=Path)
    build(parser.parse_args().llvm_directory)
