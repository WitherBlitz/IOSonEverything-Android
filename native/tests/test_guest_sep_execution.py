"""Execute the real injected AArch64 bytes with deterministic import responses.

Requires test-only `unicorn==2.1.4`. This checks control flow and ABI, not Apple's
kernel/SEP behavior; the actual restored guest still requires device testing.
"""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adapt_guest_daemon import adapt

try:
    import unicorn
    from unicorn import arm64_const as registers
except ImportError:
    unicorn = None


class Routine:
    BASE, STACK = 0x100000000, 0x200000000

    def __init__(self, test, cleanup=False, statuses=None, wait_fail=None,
                 fork_fail=None, fork_child=False, unmount_fail=None, system_unmount=False):
        self.test, self.commands, self.messages = test, [], []
        self.statuses, self.wait_fail, self.fork_fail = statuses or {}, wait_fail, fork_fail
        self.fork_child, self.stop = fork_child, None
        self.unmount_fail, self.unmounts, self.operations = unmount_fail or {}, [], []
        self.uc = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
        self.uc.mem_map(self.BASE, 0x20000)
        original = (Path(__file__).resolve().parents[2] /
                    'third_party/guest-tools-source/original-inferno_patcher').read_bytes()
        self.uc.mem_write(self.BASE, adapt(original))
        self.uc.mem_map(self.STACK, 0x10000)
        self.uc.reg_write(registers.UC_ARM64_REG_TPIDRRO_EL0, self.STACK + 0x1000)
        self.uc.mem_write(self.STACK + 0x1008, struct.pack('<Q', self.STACK + 0x2000))
        self.uc.mem_write(self.STACK + 0x2000, struct.pack('<I', 12))
        self.initial_sp = self.STACK + 0x8000
        self.uc.reg_write(registers.UC_ARM64_REG_SP, self.initial_sp)
        self.saved = {number: 0x12340000 + number for number in range(19, 30)}
        for number, value in self.saved.items():
            self.uc.reg_write(getattr(registers, 'UC_ARM64_REG_X%d' % number), value)
        self.uc.reg_write(registers.UC_ARM64_REG_X0, 0)
        if system_unmount:
            self.uc.mem_write(self.STACK + 0x3000, b'/sbin/umount\0')
            self.uc.mem_write(self.STACK + 0x3020, b'/mnt9\0')
            self.uc.mem_write(self.STACK + 0x3100, struct.pack('<3Q', self.STACK + 0x3000,
                                                            self.STACK + 0x3020, 0))
            self.uc.reg_write(registers.UC_ARM64_REG_X0, self.STACK + 0x3000)
            self.uc.reg_write(registers.UC_ARM64_REG_X1, self.STACK + 0x3100)
        self.uc.hook_add(unicorn.UC_HOOK_CODE, self.hook)
        self.uc.hook_add(unicorn.UC_HOOK_INTR, self.syscall)
        self.uc.emu_start(self.BASE + (0x45cc if system_unmount else (0x458c if cleanup else 0x40cc)),
                          self.BASE + 0x10000, timeout=2_000_000, count=20000)
        test.assertIsNotNone(self.stop, 'routine did not reach a bounded return path')
        if self.stop != 0x4660:
            test.assertEqual(self.uc.reg_read(registers.UC_ARM64_REG_SP), self.initial_sp)
            for number, value in self.saved.items():
                test.assertEqual(self.uc.reg_read(getattr(registers, 'UC_ARM64_REG_X%d' % number)),
                                 value, 'callee-saved X%d changed' % number)

    def string(self, address):
        result = bytearray()
        for offset in range(512):
            value = self.uc.mem_read(address + offset, 1)[0]
            if not value:
                return result.decode()
            result.append(value)
        raise AssertionError('unterminated string')

    def argv(self, address):
        result = []
        for index in range(8):
            pointer = struct.unpack('<Q', self.uc.mem_read(address + index * 8, 8))[0]
            if not pointer:
                return result
            result.append(self.string(pointer))
        raise AssertionError('unterminated argv')

    def hook(self, uc, address, size, _):
        offset = address - self.BASE
        if offset in (0x40d0, 0x45b0, 0x42d8, 0x4660):
            self.stop = offset
            uc.emu_stop()
            return
        if offset not in (0x46b0, 0x46c0, 0x46d0, 0x46e0, 0x4710, 0x4720, 0x47b0):
            return
        self.test.assertEqual(uc.reg_read(registers.UC_ARM64_REG_SP) % 16, 0)
        result = 0
        if offset == 0x46d0:
            args = self.argv(uc.reg_read(registers.UC_ARM64_REG_X20))
            self.test.assertEqual(args[0], self.string(uc.reg_read(registers.UC_ARM64_REG_X19)))
            self.commands.append(args)
            self.operations.append(['exec', *args])
            result = -1 if len(self.commands) == self.fork_fail else (0 if self.fork_child else 42)
        elif offset == 0x47b0:
            self.test.assertEqual(uc.reg_read(registers.UC_ARM64_REG_X0), 42)
            result = -1 if len(self.commands) == self.wait_fail else 42
            status = self.statuses.get(len(self.commands), 0)
            uc.mem_write(uc.reg_read(registers.UC_ARM64_REG_X1), struct.pack('<I', status))
        elif offset == 0x4720:
            self.messages.append(self.string(uc.reg_read(registers.UC_ARM64_REG_X0)))
        elif offset == 0x46b0:
            result = -1 # Only exercised by the child exec-failure test.
        uc.reg_write(registers.UC_ARM64_REG_X0, result & ((1 << 64) - 1))
        uc.reg_write(registers.UC_ARM64_REG_PC, uc.reg_read(registers.UC_ARM64_REG_LR))

    def syscall(self, uc, interrupt, _):
        self.test.assertEqual(uc.reg_read(registers.UC_ARM64_REG_X16), 159)
        self.test.assertEqual(uc.reg_read(registers.UC_ARM64_REG_X1), 0, 'must not force unmount')
        path = self.string(uc.reg_read(registers.UC_ARM64_REG_X0))
        self.unmounts.append(path)
        self.operations.append(['unmount', path])
        uc.reg_write(registers.UC_ARM64_REG_X0, self.unmount_fail.get(len(self.unmounts), 0))


@unittest.skipIf(unicorn is None, 'Install test-only unicorn==2.1.4 for instruction execution')
class GuestSepExecutionTests(unittest.TestCase):
    def test_prepare_runs_mount_init_load_ping_in_order(self):
        run = Routine(self)
        self.assertEqual(run.stop, 0x40d0)
        self.assertEqual(run.commands, [
            ['/sbin/mount_apfs', '-R', '/dev/disk0s1s3', '/mnt7'],
            ['/usr/libexec/seputil', '--wait', '--gigalocker-init'],
            ['/usr/libexec/seputil', '--wait', '--load', '/usr/bin/peppytool'],
            ['/usr/libexec/seputil', '--ping']])
        self.assertIn('*** PATCHER: saved SEP firmware ready', run.messages)

    def test_each_prepare_failure_prevents_later_commands_and_ready_message(self):
        for failed in range(1, 5):
            for status in (1 << 8, 9): # nonzero exit and signal
                with self.subTest(command=failed, status=status):
                    run = Routine(self, statuses={failed: status})
                    self.assertEqual(run.stop, 0x42d8)
                    self.assertEqual(len(run.commands), failed)
                    self.assertNotIn('*** PATCHER: saved SEP firmware ready', run.messages)

    def test_fork_and_wait_failures_cannot_report_ready(self):
        for options in ({'fork_fail': 1}, {'wait_fail': 2}):
            run = Routine(self, **options)
            self.assertEqual(run.stop, 0x42d8)
            self.assertNotIn('*** PATCHER: saved SEP firmware ready', run.messages)

    def test_child_exec_failure_exits_127(self):
        run = Routine(self, fork_child=True)
        self.assertEqual(run.stop, 0x4660)
        self.assertEqual(run.uc.reg_read(registers.UC_ARM64_REG_X0), 127)

    def test_cleanup_waits_for_verified_data_unmount(self):
        run = Routine(self, cleanup=True, unmount_fail={1: 16})
        self.assertEqual(run.stop, 0x42d8)
        self.assertEqual(run.commands, [])
        self.assertEqual(run.unmounts, ['/mnt8'])

    def test_cleanup_closes_key_store_then_unmounts_xart(self):
        run = Routine(self, cleanup=True)
        self.assertEqual(run.stop, 0x45b0)
        self.assertEqual(run.operations, [['unmount', '/mnt8'],
                                          ['exec', '/usr/libexec/seputil', '--gigalocker-shutdown'],
                                          ['unmount', '/mnt7']])
        self.assertIn('*** PATCHER: done, the machine can be reset now', run.messages)

    def test_cleanup_failure_never_prints_done(self):
        for options in ({'statuses': {1: 1 << 8}}, {'wait_fail': 1}, {'unmount_fail': {2: 16}}):
            run = Routine(self, cleanup=True, **options)
            self.assertEqual(run.stop, 0x42d8)
            self.assertNotIn('*** PATCHER: done, the machine can be reset now', run.messages)

    def test_original_system_umount_uses_checked_syscall_and_exit_status(self):
        for result in (0, 16):
            run = Routine(self, system_unmount=True, unmount_fail={1: result})
            self.assertEqual(run.stop, 0x4660)
            self.assertEqual(run.uc.reg_read(registers.UC_ARM64_REG_X0), result)
            self.assertEqual(run.unmounts, ['/mnt9'])
            self.assertEqual(run.commands, [])
