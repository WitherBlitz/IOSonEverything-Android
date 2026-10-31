/* Firmware-free A13 test for the opt-in TCG guest GPU channel. */
.text
.global _start
_start:
 ldr x16, =0x494f534750553031
 mov x0, #0
 mov x1, #0
 mov x2, #0
 mov x3, #0
 mov x4, #0
 mov x5, #0
 hlt #0x4f53
 ldr x2, =0x47505531
 cmp x0, x2
 b.ne fail
 ldr x0, =0x50415353
 b result
fail:
 mov x0, #1
result:
 ldr x1, =0x200000000
 str x2, [x1]
 str x0, [x1, #8]
1: wfe
 b 1b
