"""Compile the real helper into a firmware-free WebAssembly unit harness; no device actions."""
from pathlib import Path
import argparse,json,subprocess

parser=argparse.ArgumentParser();parser.add_argument('--expect-fail',action='store_true');args=parser.parse_args()
here=Path(__file__).resolve().parent
root=here.parents[5]
tool=root/'work/tools/android-sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64/bin'
out=root/'work/gpu-pipeline/host-research/rpc-memory-harness'
out.mkdir(exist_ok=True)
qemu=here.parents[2]/'third_party/inferno'
command=[tool/'clang.exe','--target=wasm32-unknown-unknown','-ffreestanding','-nostdlib','-fno-builtin',
 '-O1','-Wall','-Wextra','-Werror','-Wno-unused-function','-I'+str(here/'rpc_memory_stubs'),
 '-I'+str(qemu/'include'),'-Wl,--no-entry','-Wl,--export=run_tests','-Wl,--export-memory',
 '-Wl,--initial-memory=262144',here/'rpc_memory_harness.c','-o',out/'test.wasm']
p=subprocess.run([str(a) for a in command],capture_output=True,timeout=30)
if p.returncode:raise SystemExit((p.stdout+p.stderr).decode(errors='replace'))
js='const fs=require("fs");WebAssembly.instantiate(fs.readFileSync(process.argv[1])).then(x=>{console.log(x.instance.exports.run_tests());});'
p=subprocess.run(['node','-e',js,str(out/'test.wasm')],capture_output=True,timeout=10)
if p.returncode:raise SystemExit((p.stdout+p.stderr).decode(errors='replace'))
mask=int(p.stdout.decode().strip());names=['bad request pointer','denied request page','request MMIO','read-only output',
 'output MMIO','preflight bad output','valid cross-page input','cross-page denied input','overlong backend reply',
 'output mapping revoked during RPC','watchpoint rejected','whole output capacity preflighted','RAM-only permission probe path',
 'foreign TTBR/ASID rejected before backend','successful close releases owner slot','open registers caller address space']
result={'scope':'helper unit test with modeled probe; no guest kernel or real QEMU MMU',
 'failed_mask':mask,'passed':sum(not(mask>>i&1) for i in range(len(names))),
 'total':len(names),'failed_cases':[n for i,n in enumerate(names) if mask>>i&1],
 'compile_argv':[str(a) for a in command]}
name='red.json' if args.expect_fail else 'green.json'
(out/name).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
raise SystemExit(0 if (bool(mask) if args.expect_fail else not mask) else 1)
