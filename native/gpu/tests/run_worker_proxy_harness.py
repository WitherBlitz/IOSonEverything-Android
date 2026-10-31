"""Run actual C proxy/worker control flow against deterministic OS/driver substitutes."""
from pathlib import Path
import json,subprocess
here=Path(__file__).resolve().parent
root=here.parents[5]
tool=root/'work/tools/android-sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64/bin'
out=root/'work/gpu-pipeline/host-research/worker-proxy-harness'
out.mkdir(exist_ok=True)
stubs=here/'worker_proxy_stubs'
headers=['dlfcn.h','errno.h','fcntl.h','poll.h','pthread.h','signal.h','spawn.h','stdio.h','stdlib.h','string.h','time.h','unistd.h','stdatomic.h',
 'sys/socket.h','sys/types.h','sys/wait.h','sys/prctl.h','sys/mman.h','sys/stat.h']
for name in headers:
 p=stubs/name;p.parent.mkdir(exist_ok=True,parents=True);p.write_text('#include "'+('../' if '/' in name else '')+'shim.h"\n')
command=[tool/'clang.exe','--target=wasm32-unknown-unknown','-ffreestanding','-nostdlib','-fno-builtin',
 '-O1','-Wall','-Wextra','-Werror','-Wno-unused-function','-I'+str(stubs),
 '-Wl,--no-entry','-Wl,--export=run_tests','-Wl,--initial-memory=134217728',
 here/'worker_proxy_harness.c','-o',out/'test.wasm']
p=subprocess.run([str(a) for a in command],capture_output=True,timeout=30)
if p.returncode:raise SystemExit((p.stdout+p.stderr).decode(errors='replace'))
js='const fs=require("fs");WebAssembly.instantiate(fs.readFileSync(process.argv[1])).then(x=>console.log(x.instance.exports.run_tests()>>>0));'
p=subprocess.run(['node','-e',js,str(out/'test.wasm')],capture_output=True,timeout=10)
if p.returncode:raise SystemExit((p.stdout+p.stderr).decode(errors='replace'))
mask=int(p.stdout.decode().strip())
names=['complete partial-I/O+EINTR reply and filtered exec environment','absolute deadline','reply sequence mismatch',
 'over-capacity reply','truncated header leaves caller untouched','fatal backend error','broken session never respawns',
 'validation errno remains signed and nonfatal','mutex queue deadline','oversized caller rejected before spawn',
 'kernel-stuck reap remains bounded','real worker framing/backend path','real worker oversized request rejected',
 'real worker parent-death race rejected','trickle bytes cannot reset deadline','stalled request write is bounded',
 'Metal opcode is admitted by proxy and private worker framing',
 'short successful stream read leaves caller untouched',
 'short successful resource download leaves caller untouched',
 'resource download accepts exact rectangle span in larger capacity',
 'response payload is shared rather than sent through the socket',
 'uncommitted shared generation never publishes bytes',
 'memfd creation failure refuses before spawn',
 'missing size seals refuses before spawn',
 'mapping failure refuses before spawn',
 'wrong shared file size refuses before spawn',
 'corrupted shared metadata never publishes bytes',
 'successive calls require their own generation',
 'worker rejects nonzero initial shared generation',
 'request bytes use non-overlapping shared storage without socket payload',
 'real worker consumes mapped request without receiving payload bytes',
 'stale request generations are refused by both proxy and worker']
result={'scope':'actual C proxy and worker with modeled OS/driver; no real spawn, kernel or device',
 'failed_mask':mask,'passed':sum(not(mask>>i&1) for i in range(len(names))),'total':len(names),
 'failed_cases':[n for i,n in enumerate(names) if mask>>i&1],'compile_argv':[str(a) for a in command]}
(out/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
raise SystemExit(bool(mask))
