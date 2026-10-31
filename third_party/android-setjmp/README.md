# QEMU context-switch compatibility

Files copied unchanged from termux/termux-packages revision
`e02748430d74d980fc28587a2d3fdd3881aad57c`, directory
`packages/qemu-system-x86-64-headless/setjmp-aarch64`, with the upstream
`private-` filenames placed in the `private/` directory as its build recipe does.

Source: https://github.com/termux/termux-packages/tree/e02748430d74d980fc28587a2d3fdd3881aad57c/packages/qemu-system-x86-64-headless/setjmp-aarch64

Background: https://github.com/termux/termux-packages/issues/12261

Every source file retains its AOSP/BSD copyright and redistribution conditions.
The generated library exports only `iossetjmp` and `ioslongjmp` under the LIBC
symbol version. The build changes private entry visibility for those exports and
turns the upstream commented checksum-failure branch into a local trap. All other
functions are hidden by the version script. Android's libc is neither patched nor
interposed: only QEMU's two undefined imports are renamed, without changing any
machine instructions. This is a fiber context implementation for QEMU's coroutine
migration, which cannot use a thread-bound signed return address.

On the S26 Ultra, the original libc version passes 10,000 same-thread switches
and crashes with a PAC exception when the context migrates threads. This library
passes 10,000 migrated switches; a real QEMU blockdev-create job also completes.
Those checks establish context switching, not an iOS GUI boot.
