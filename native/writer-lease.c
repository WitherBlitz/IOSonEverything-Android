/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Executable QEMU writer ownership; loaded before QEMU opens any guest files. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <unistd.h>

static int writer_fd = -1;

static void refuse(void) {
    static const char message[] = "error: QEMU writer has no live owner or exclusive disk lease\n";
    (void)write(2, message, sizeof(message) - 1);
    _exit(75);
}

__attribute__((constructor)) static void writer_lease(void) {
    const char *path = getenv("IOSVM_WRITER_LOCK");
    const char *parent = getenv("IOSVM_WRITER_PARENT");
    /* In-process QEMU is protected by its Java service's kernel-held lease. */
    if (!path && !parent) return;
    if (!path || path[0] != '/' || !parent) refuse();
    char *end;
    errno = 0;
    long expected = strtol(parent, &end, 10);
    if (errno || *end || expected <= 1 || expected > 2147483647L) refuse();
    /* Close the fork/exec-to-constructor race, including an already dead parent. */
    if (prctl(PR_SET_PDEATHSIG, SIGTERM) || getppid() != (pid_t)expected) refuse();
    writer_fd = open(path, O_RDWR | O_CREAT | O_CLOEXEC, 0600);
    if (writer_fd < 0) refuse();
    struct flock lock = {.l_type = F_WRLCK, .l_whence = SEEK_SET, .l_start = 0, .l_len = 0};
    int result;
    do { result = fcntl(writer_fd, F_SETLK, &lock); } while (result < 0 && errno == EINTR);
    if (result < 0 || getppid() != (pid_t)expected) refuse();
    /* Keep the descriptor until actual process exit, including a delayed SIGTERM. */
}
