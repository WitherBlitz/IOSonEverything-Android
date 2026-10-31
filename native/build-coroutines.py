"""Build the QEMU-only context switch library using an Android NDK.

Upstream source remains unmodified in third_party/android-setjmp. Export only
the two names used by our engine; retain checksum validation with a local trap.
"""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build(ndk, output):
    toolchains = list((ndk / 'toolchains/llvm/prebuilt').glob('*'))
    if len(toolchains) != 1:
        raise ValueError('Expected one NDK host toolchain')
    binaries = toolchains[0] / 'bin'
    compiler = binaries / ('clang.exe' if (binaries / 'clang.exe').exists() else 'clang')
    source_dir = ROOT / 'third_party/android-setjmp'
    output.mkdir(parents=True, exist_ok=True)
    source = (source_dir / 'setjmp.S').read_text()
    source = source.replace('ENTRY_PRIVATE(', 'ENTRY(')
    source = source.replace('//bne __bionic_setjmp_checksum_mismatch', 'bne .Lbad_context')
    source += '\n.text\n.Lbad_context:\n  brk #0\nNOTE_GNU_PROPERTY()\n'
    generated = output / 'ios-coroutines.S'
    generated.write_text(source)
    version = output / 'coroutines.map'
    version.write_text('LIBC { global: iossetjmp; ioslongjmp; local: *; };\n')
    library = output / 'libios_coroutines.so'
    subprocess.run([str(compiler), '--target=aarch64-linux-android34', '-O2',
                    '-fPIC', '-shared', '-mbranch-protection=bti',
                    '-Dsigsetjmp=iossetjmp', '-Dsiglongjmp=ioslongjmp',
                    '-I' + str(source_dir), str(generated), str(ROOT / 'native/writer-lease.c'),
                    '-Wl,-z,relro,-z,now,-z,noexecstack,-z,global',
                    '-Wl,-soname,libios_coroutines.so',
                    '-Wl,--version-script=' + str(version), '-o', str(library)], check=True)
    return library


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ndk', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(build(args.ndk.resolve(), args.output.resolve()))
