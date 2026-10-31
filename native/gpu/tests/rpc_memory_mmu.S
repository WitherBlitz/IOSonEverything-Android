/* Bare-metal a13-test regression: real EL1 permissions, 16 KiB pages.
 * No Apple firmware or data. PING with buffers must fail shape validation only
 * after valid RAM is probed; inaccessible/RO/MMIO buffers must fail EFAULT first.
 * No graphics context is opened. SPDX-License-Identifier: AGPL-3.0-or-later */
.set RAM, 0x800000000
.set CTL, 0x200000000
.set L2, RAM+0x100000
.set L3, L2+0x4000
.set DATA, RAM+0x200000
.set VA, 0xA00000000
.set TCR, 28|(1<<8)|(1<<10)|(3<<12)|(2<<14)|(28<<16)|(1<<23)|(1<<30)|(1<<32)
.text
.global _start
_start:
 mov x19,#0
 adr x0,vectors
 msr vbar_el1,x0
 ldr x0,=L2
 mov x1,#0x1000
1: str xzr,[x0],#8
 subs x1,x1,#1
 b.ne 1b
 ldr x0,=L2
 ldr x1,=RAM|0x701
 str x1,[x0,#0x400*8]
 ldr x1,=CTL|0x0060000000000405
 str x1,[x0,#0x100*8]
 ldr x1,=L3|3
 str x1,[x0,#0x500*8]
 ldr x0,=L3
 ldr x1,=DATA|0x703
 str x1,[x0]
 add x1,x1,#4,lsl #12
 str x1,[x0,#8]
 add x1,x1,#4,lsl #12
 orr x1,x1,#0x80
 str x1,[x0,#16]
 ldr x0,=0xff
 msr mair_el1,x0
 ldr x0,=TCR
 msr tcr_el1,x0
 ldr x0,=L2
 msr ttbr0_el1,x0
 dsb ish
 tlbi vmalle1
 dsb ish
 isb
 mrs x0,sctlr_el1
 orr x0,x0,#1
 orr x0,x0,#4
 orr x0,x0,#(1<<12)
 bic x0,x0,#(1<<1)
 bic x0,x0,#(1<<19)
 msr sctlr_el1,x0
 isb
 .macro RPC input, size, output, capacity, expected
 add x19,x19,#1
 ldr x16,=0x494f534750553031
 mov x0,#0
 mov x1,#0
 ldr x2,=\input
 mov x3,#\size
 ldr x4,=\output
 mov x5,#\capacity
 hlt #0x4f53
 ldr x9,=\expected
 cmp x0,x9
 b.ne failed
 cbnz x1,failed
 .endm
 RPC 0,0,0,0,0x47505531
 RPC VA,8,0,0,-22
 RPC 0,0,VA,8,-22
 RPC 0,0,VA+0x8000,8,-14
 RPC VA+0xc000,8,0,0,-14
 RPC VA+0x3ff8,16,0,0,-22
 RPC VA+0xbff8,16,0,0,-14
 RPC CTL,8,0,0,-14
 RPC 0,0,CTL,8,-14
 RPC 0,0,VA+0x7ff8,16,-14
 RPC VA+0x8000,8,0,0,-22
 /* A second address space/ASID may not close the first one's context. */
 add x19,x19,#1
 ldr x16,=0x494f534750553031
 mov x0,#1
 mov x1,#0
 mov x2,#0
 mov x3,#0
 mov x4,#0
 mov x5,#0
 hlt #0x4f53
 cmp x0,#0
 b.le failed
 mov x20,x0
 ldr x9,=L2|(1<<48)
 msr ttbr0_el1,x9
 isb
 add x19,x19,#1
 mov x0,#4
 mov x1,x20
 hlt #0x4f53
 mov x9,#-13
 cmp x0,x9
 b.ne failed
 ldr x9,=L2
 msr ttbr0_el1,x9
 isb
 add x19,x19,#1
 mov x0,#4
 mov x1,x20
 hlt #0x4f53
 cbnz x0,failed
 ldr x0,=0x50415353
 b result
failed:
 mov x2,x0
 ldr x0,=0x46000000
 orr x0,x0,x19
 b report
unexpected:
 mrs x2,esr_el1
 ldr x0,=0x47000000
 orr x0,x0,x19
 b report
result:
 mov x2,x19
report:
 ldr x1,=CTL
 str x2,[x1]
 str x0,[x1,#8]
2: wfe
 b 2b
.balign 2048
vectors:
.rept 16
 b unexpected
 .space 124
.endr
