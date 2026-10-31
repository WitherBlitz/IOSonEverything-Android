import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import ExitStack
from types import SimpleNamespace
from iosvm import installer
from iosvm.installer import record_restore_checkpoint, BOOT_FILES
from iosvm.acquisition import cleanup_staging, find_restore_checkpoint, recover_installation


class RestoreCheckpointTests(unittest.TestCase):
    def restored(self, base):
        stage = base / 'ios-staging-123'; stage.mkdir()
        for name in BOOT_FILES:
            (stage / name).write_bytes(b'test guest file')
        root = bytearray(8192); root[512:520] = b'EFI PART'
        (stage / 'root').write_bytes(root)
        (stage / 'ramdisk').write_bytes(b'stock ramdisk')
        with patch('iosvm.installer.DISKS', {'root': 8192}):
            record_restore_checkpoint(stage)
        return stage

    def test_completed_restore_survives_patch_failure_cleanup_and_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); stage = self.restored(base)
            cleanup_staging(base)
            self.assertEqual(find_restore_checkpoint(base), stage.resolve())
            self.assertIsNone(recover_installation(base))
            self.assertTrue((stage / 'root').is_file())

    def test_checkpoint_does_not_preserve_corrupted_static_input(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); stage = self.restored(base)
            (stage / 'kernel').write_bytes(b'same size? bad!')
            self.assertIsNone(find_restore_checkpoint(base))
            cleanup_staging(base)
            self.assertFalse(stage.exists())

    def test_checkpoint_requires_successful_restore_and_valid_gpt(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); stage = self.restored(base)
            (stage / 'root').write_bytes(bytes(8192))
            self.assertIsNone(find_restore_checkpoint(base))

    def test_checkpoint_is_never_promoted_as_a_patched_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); self.restored(base)
            self.assertIsNone(recover_installation(base))
            self.assertFalse((base / 'ios-current').exists())

    def resumed_install(self, base, succeeds, failure=None):
        callback = SimpleNamespace(update=lambda *_: None, isCancelled=lambda: False)
        markers = ['*** PATCHER: the patcher exited with 0',
                   '*** PATCHER: saved SEP firmware ready',
                   '*** PATCHER: unmount /mnt9 result=0',
                   '*** PATCHER: unmount /mnt8 result=0',
                   '*** PATCHER: unmount /mnt7 result=0',
                   '*** PATCHER: five services switched off',
                   '*** PATCHER: done, the machine can be reset now'] if succeeds else []
        machine = SimpleNamespace(console=[failure] if failure else markers,
                                  process=SimpleNamespace(poll=lambda: None if failure else 1), stop=lambda: None)
        with ExitStack() as context:
            for name in ('acquire', 'prepare', 'RestoreClient'):
                context.enter_context(patch.object(installer, name, side_effect=AssertionError('Full restore must be skipped')))
            context.enter_context(patch.object(installer, 'ASSET_HASHES', {}))
            context.enter_context(patch.object(installer, 'DISKS', {'root': 8192}))
            context.enter_context(patch.object(installer.shutil, 'disk_usage', return_value=SimpleNamespace(free=5 * 1024**3)))
            context.enter_context(patch.object(installer, 'patch_ramdisk'))
            context.enter_context(patch.object(installer, 'Muxd'))
            context.enter_context(patch.object(installer, 'Machine', return_value=machine))
            if failure:
                context.enter_context(patch.object(installer.time, 'sleep',
                                                  side_effect=AssertionError('Failure must stop immediately')))
            installer.install(base, base / 'native', base / 'resources', callback)

    def test_offline_resume_with_five_gb_free_skips_acquisition_and_full_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); self.restored(base)
            self.resumed_install(base, succeeds=True)
            self.assertTrue((base / 'ios-current/installation.json').is_file())
            self.assertFalse((base / 'ios-downloads/18A5351d.ipsw').exists())

    def test_failed_offline_resume_preserves_successful_restore_for_another_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); stage = self.restored(base)
            with self.assertRaisesRegex(RuntimeError, 'patching did not finish'):
                self.resumed_install(base, succeeds=False)
            self.assertEqual(find_restore_checkpoint(base), stage.resolve())
            self.assertFalse((base / 'ios-current').exists())

    def test_explicit_helper_failure_stops_live_machine_and_retains_checkpoint(self):
        for failure in ('*** PATCHER: saved SEP preparation failed',
                        '*** PATCHER: saved SEP cleanup failed'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                base = Path(directory); stage = self.restored(base)
                with self.assertRaisesRegex(RuntimeError, 'failed'):
                    self.resumed_install(base, succeeds=False, failure=failure)
                self.assertEqual(find_restore_checkpoint(base), stage.resolve())
                self.assertFalse((base / 'ios-current').exists())
