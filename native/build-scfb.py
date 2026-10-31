"""Build the retained AVF display/camera helper from source with NDK r28c."""
import argparse
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('ndk', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
toolchains = list((args.ndk.resolve() / 'toolchains/llvm/prebuilt').glob('*'))
if len(toolchains) != 1:
    raise SystemExit('Expected one NDK host toolchain')
binary = toolchains[0] / 'bin'
suffix = '.exe' if (binary / 'clang.exe').exists() else ''
args.output.mkdir(parents=True, exist_ok=True)
unstripped = args.output.resolve() / 'libscfb-unstripped.so'
library = args.output.resolve() / 'libscfb.so'
subprocess.run([str(binary / ('clang' + suffix)), '--target=aarch64-linux-android31',
    '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
    '-Wl,-z,max-page-size=16384', '-Wl,-soname,libscfb.so',
    str(root / 'app/src/main/cpp/scfb_present.c'), str(root / 'app/src/main/cpp/sccam_put.c'),
    '-landroid', '-llog', '-o', str(unstripped)], check=True)
subprocess.run([str(binary / ('llvm-strip' + suffix)), '--strip-unneeded',
                str(unstripped), '-o', str(library)], check=True)
print(library)
