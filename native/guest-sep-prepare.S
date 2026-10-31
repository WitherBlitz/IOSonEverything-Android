// Post-restore cold ramdisk boot. The original full restore starts SEP itself;
// the patch-only boot must first attach the existing xART volume and gigalocker.
// All commands act on this guest's saved state. No erase/restore commands occur.
// Assemble as AArch64 ELF, extract .text, then retain [0x1200, sep_code_end).
.text
.org 0x1200
.global guest_sep_prepare
guest_sep_prepare:
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    sub sp, sp, #64
    bl original_fflush // original call replaced by the hook; x0 is stdout
    adr x0, xart_mount
    mov w1, #0x1ed
    bl original_mkdir

    adr x0, mount_program
    adr x8, mount_option
    stp x0, x8, [sp]
    adr x8, xart_device
    adr x9, xart_mount
    stp x8, x9, [sp, #16]
    str xzr, [sp, #32]
    mov x1, sp
    bl run_child
    cbnz w0, prepare_failed

    adr x0, sep_program
    adr x8, wait_option
    stp x0, x8, [sp]
    adr x8, init_option
    stp x8, xzr, [sp, #16]
    mov x1, sp
    bl run_child
    cbnz w0, prepare_failed

    adr x0, sep_program
    adr x8, wait_option
    stp x0, x8, [sp]
    adr x8, load_option
    adr x9, sep_payload
    stp x8, x9, [sp, #16]
    str xzr, [sp, #32]
    mov x1, sp
    bl run_child
    cbnz w0, prepare_failed

    adr x0, sep_program
    adr x8, ping_option
    stp x0, x8, [sp]
    str xzr, [sp, #16]
    mov x1, sp
    bl run_child
    cbnz w0, prepare_failed

    adr x0, prepare_ready
    bl original_puts
    mov x0, xzr
    bl original_fflush
    add sp, sp, #64
    ldp x29, x30, [sp], #16
    ret

prepare_failed:
    adr x0, prepare_error
    bl original_puts
    mov x0, xzr
    bl original_fflush
    add sp, sp, #64
    ldp x29, x30, [sp], #16
    b original_failure // restore original main's frame and return failure

// Replace the original inlined Data umount fork with the guest syscall: this
// selected restore ramdisk contains no umount executable at any usual path.
// Keep xART attached until the key-store client finishes, then close it cleanly.
.global guest_sep_cleanup
guest_sep_cleanup:
    sub sp, sp, #64
    stp x19, x30, [sp, #48]
    adr x19, original_done_message
    adr x0, data_mount
    bl unmount_guest
    cbnz w0, cleanup_failed
    adr x0, sep_program
    adr x8, shutdown_option
    stp x0, x8, [sp]
    str xzr, [sp, #16]
    mov x1, sp
    bl run_child
    cbnz w0, cleanup_failed
    adr x0, xart_mount
    bl unmount_guest
    cbnz w0, cleanup_failed
    mov x0, x19
    bl original_puts
    ldp x19, x30, [sp, #48]
    add sp, sp, #64
    b original_done_fflush
cleanup_failed:
    adr x0, cleanup_error
    bl original_puts
    mov x0, xzr
    bl original_fflush
    ldp x19, x30, [sp, #48]
    add sp, sp, #64
    b original_failure

// int run_child(path, argv). No output redirection; Darwin printf varargs use
// stack slots. Preserve all callee-saved registers we use and the unsigned LR.
run_child:
    sub sp, sp, #64
    stp x19, x20, [sp, #32]
    str x30, [sp, #48]
    mov x19, x0
    mov x20, x1
    str x19, [sp]
    ldr x8, [x20, #8]
    str x8, [sp, #8]
    adr x0, exec_message
    bl original_printf
    mov x0, xzr
    bl original_fflush
    bl original_fork
    tbnz w0, #31, child_failed
    cbnz w0, wait_child
    mov x0, x19
    mov x1, x20
    bl original_execv
    // Exact selected iOS14 libsystem_kernel __error implementation uses this
    // TLS slot (4794..479c). Read immediately, before printf can change errno.
    mrs x8, TPIDRRO_EL0
    and x8, x8, #0xfffffffffffffff8
    ldr x8, [x8, #8]
    cbz x8, errno_unavailable
    ldr w8, [x8]
    b print_exec_error
errno_unavailable:
    mov w8, #-1
print_exec_error:
    stp x19, x8, [sp]
    adr x0, exec_failed
    bl original_printf
    mov x0, xzr
    bl original_fflush
    mov w0, #127
    bl original_exit
wait_child:
    str wzr, [sp, #16]
    add x1, sp, #16
    mov w2, #0
    bl original_waitpid
    str x0, [sp, #24]
    ldr w8, [sp, #16]
    stp x19, x8, [sp]
    adr x0, command_status
    bl original_printf
    mov x0, xzr
    bl original_fflush
    ldr w0, [sp, #24]
    tbnz w0, #31, child_failed
    ldr w8, [sp, #16]
    and w9, w8, #0x7f
    cbnz w9, child_signalled
    ubfx w0, w8, #8, #8
    b child_return
child_signalled:
    neg w0, w9
    b child_return
child_failed:
    mov w0, #-1
child_return:
    ldp x19, x20, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    ret

mount_program: .asciz "/sbin/mount_apfs"
umount_program: .asciz "/sbin/umount"
mount_option: .asciz "-R"
xart_device: .asciz "/dev/disk0s1s3"
xart_mount: .asciz "/mnt7"
data_mount: .asciz "/mnt8"
sep_program: .asciz "/usr/libexec/seputil"
init_option: .asciz "--gigalocker-init"
wait_option: .asciz "--wait"
load_option: .asciz "--load"
sep_payload: .asciz "/usr/bin/peppytool"
ping_option: .asciz "--ping"
shutdown_option: .asciz "--gigalocker-shutdown"
prepare_ready: .asciz "*** PATCHER: saved SEP firmware ready"
prepare_error: .asciz "*** PATCHER: saved SEP preparation failed"
cleanup_error: .asciz "*** PATCHER: saved SEP cleanup failed"
command_status: .asciz "*** PATCHER: %s child status=%d\n"
exec_failed: .asciz "*** PATCHER: exec %s returned errno=%d\n"
exec_message: .asciz "*** PATCHER: executing %s %s\n"
.balign 4

// The original common exec path also asks for /sbin/umount after System. Match
// that exact path; all other commands retain the existing authenticated execv.
.org 0x1700
.global guest_exec_dispatch
guest_exec_dispatch:
    adr x2, umount_program
    mov x3, x0
match_umount:
    ldrb w4, [x3], #1
    ldrb w5, [x2], #1
    cmp w4, w5
    b.ne exec_other
    cbnz w4, match_umount
    ldr x0, [x1, #8]
    bl unmount_guest
    bl original_exit
exec_other:
    b original_execv

.org 0x1780
// Darwin iOS14 libsystem_kernel _unmount at2a634 uses SYS159/SVC0x80.
// Flags0: normal checked unmount, without force. Kernel error is returned in x0.
unmount_guest:
    sub sp, sp, #48
    stp x19, x30, [sp, #32]
    mov x19, x0
    mov x1, xzr
    mov x16, #159
    svc #0x80
    str x0, [sp, #16]
    stp x19, x0, [sp]
    adr x0, unmount_message
    bl original_printf
    mov x0, xzr
    bl original_fflush
    ldr x0, [sp, #16]
    ldp x19, x30, [sp, #32]
    add sp, sp, #48
    ret
unmount_message: .asciz "*** PATCHER: unmount %s result=%d\n"
.org 0x1900
.global sep_code_end
sep_code_end:

// Existing offsets in the exact hash-pinned Mach-O. These labels resolve the
// relative instructions without introducing relocations into the copied code.
.org 0x42d8
original_failure: nop
.org 0x45b0
original_done_fflush: nop
.org 0x4660
original_exit: nop
.org 0x46b0
original_execv: nop
.org 0x46c0
original_fflush: nop
.org 0x46d0
original_fork: nop
.org 0x46e0
original_mkdir: nop
.org 0x4710
original_printf: nop
.org 0x4720
original_puts: nop
.org 0x47b0
original_waitpid: nop
.org 0x4bbc
original_done_message: nop
