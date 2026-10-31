// Darwin arm64 variadic arguments go on the stack. This diagnostic trampoline
// runs only in the forked child immediately before the existing execv call.
.text
.global guest_exec_trace
guest_exec_trace:
    sub sp, sp, #48
    stp x0, x1, [sp, #32]
    str x0, [sp]
    ldr x2, [x1, #8]
    str x2, [sp, #8]
    nop // filled with ADR x0, format
    nop // filled with BL existing printf stub
    mov x0, xzr
    nop // filled with BL existing fflush stub (NULL flushes all streams)
    ldp x0, x1, [sp, #32]
    add sp, sp, #48
    nop // filled with ADR x30, original execv return site
    nop // filled with B existing execv stub
