import pathlib
import tempfile
import unittest
from iosvm.installer import record_installation, seed_firmware, command
from iosvm.firmware import tlv, personalize


class InstallerTests(unittest.TestCase):
    def test_patch_boot_mounts_ramdisk_without_requesting_nand_reformat(self):
        args = command('engine', pathlib.Path('stage'), pathlib.Path('resources'),
                       '/private/usb.sock', 'ramdisk-patched', patch_only=True)
        self.assertIn('boot-mode=exit_recovery', args[args.index('-M') + 1])
        boot_args = args[args.index('-append') + 1].split()
        self.assertNotIn('-restore', boot_args)
        self.assertIn('rd=md0', boot_args)
        self.assertFalse(any(arg.startswith('nand-enable-reformat=') for arg in boot_args))

    def test_first_restore_boot_has_ticket_inside_firmware_partition(self):
        with tempfile.TemporaryDirectory() as directory:
            disk = pathlib.Path(directory) / 'firmware'
            disk.write_bytes(bytes(4096))
            llb = tlv(0x30, tlv(0x16, b'IM4P') + tlv(0x16, b'illb') + tlv(0x16, b'test') + tlv(4, b'payload'))
            ticket = tlv(0x30, tlv(0x16, b'IM4M'))
            expected = personalize(llb, ticket)
            seed_firmware(disk, llb, ticket)
            self.assertEqual(disk.stat().st_size, 4096)
            self.assertEqual(disk.read_bytes()[:len(expected)], expected)
            self.assertEqual(disk.read_bytes()[len(expected):], bytes(4096 - len(expected)))

    def test_restore_success_without_all_patch_markers_cannot_be_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            with self.assertRaisesRegex(ValueError, 'patch'):
                record_installation(path, ['*** PATCHER: done, the machine can be reset now'])
            self.assertFalse((path / 'installation.json').exists())

    def test_patcher_failure_overrides_final_done_message(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'patch'):
                record_installation(pathlib.Path(directory), [
                    '*** PATCHER: the patcher exited with 1',
                    '*** PATCHER: five services switched off',
                    '*** PATCHER: done, the machine can be reset now'])

    def test_missing_verified_unmounts_cannot_promote_a_guest(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'patch'):
                record_installation(pathlib.Path(directory), [
                    '*** PATCHER: the patcher exited with 0',
                    '*** PATCHER: five services switched off',
                    '*** PATCHER: done, the machine can be reset now'])
