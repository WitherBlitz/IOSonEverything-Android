"""Build only; parent runs the binary with the rebuilt opt-in a13-test engine."""
from pathlib import Path
import json,subprocess
here=Path(__file__).resolve().parent
root=here.parents[5]
binary=root/'work/tools/android-sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64/bin'
out=root/'work/gpu-pipeline/host-research/rpc-memory-mmu'
out.mkdir(exist_ok=True)
commands=[[binary/'clang.exe','--target=aarch64-none-elf','-c',here/'rpc_memory_mmu.S','-o',out/'test.o'],
 [binary/'ld.lld.exe','-m','aarch64elf','-Ttext=0x800000000','-e','_start',out/'test.o','-o',out/'test.elf'],
 [binary/'llvm-objcopy.exe','-O','binary',out/'test.elf',out/'test.bin']]
records=[]
for command in commands:
 p=subprocess.run([str(a) for a in command],capture_output=True,timeout=30)
 records.append({'argv':[str(a) for a in command],'exit_code':p.returncode,
                 'output':(p.stdout+p.stderr).decode(errors='replace')})
 (out/'build.json').write_text(json.dumps(records,indent=2)+'\n')
 if p.returncode:raise SystemExit(records[-1]['output'])
print(json.dumps({'binary':str(out/'test.bin'),'built':True,'executed':False,'checks':14},indent=2))
