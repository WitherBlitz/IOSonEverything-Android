import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ios16_installer.persistence import create_data_store, INITIAL_SHA256, STORE_AT, STORE_BYTES
from ios16_installer.safety import Hooks
from iosvm import installer16 as module


class Crash(BaseException):
    pass


def completed(path, label=b'new immutable bytes'):
    path.mkdir(parents=True)
    files = {}
    for name in module.IMMUTABLE:
        (path / name).write_bytes(label)
        files[name] = {'bytes': len(label), 'sha256': hashlib.sha256(label).hexdigest()}
    create_data_store(path / 'data.store')
    files['data.store'] = {'bytes': STORE_BYTES, 'sha256': INITIAL_SHA256,
                          'mutable': True, 'sha256_is_initial_only': True}
    (path / 'installation.json').write_text(json.dumps({'schema_version': 1, 'profile': module.PROFILE,
        'prepared': True, 'kernel_patches_verified': True, 'files': files,
        'gui_boot_verified': False, 'input_verified': False, 'persistence_verified': False}))
    return path


class Installer16Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.old = completed(self.base / 'ios16-current', b'old immutable bytes')
        self.stage = completed(self.base / 'ios16-preparation/runs/preparation-test/final')
        self.sentinel = self.base / 'ios-current'
        self.sentinel.mkdir()
        (self.sentinel / 'data').write_bytes(b'never touch iOS14')
        self.marker = b'essential mutable user data'
        with (self.old / 'data.store').open('r+b') as stream:
            stream.seek(STORE_AT + 4096); stream.write(self.marker)

    def user_data(self, directory):
        with (directory / 'data.store').open('rb') as stream:
            stream.seek(STORE_AT + 4096); return stream.read(len(self.marker))

    def check14(self):
        self.assertEqual(b'never touch iOS14', (self.sentinel / 'data').read_bytes())
        self.assertEqual({'data'}, {p.name for p in self.sentinel.iterdir()})

    def test_repair_promotes_verified_files_and_preserves_data_and_initial_provenance(self):
        result = module.promote(self.base, self.stage)
        self.assertEqual(self.old, result)
        self.assertEqual(b'new immutable bytes', (result / 'Image').read_bytes())
        self.assertEqual(self.marker, self.user_data(result))
        receipt = json.loads((result / 'installation.json').read_text())
        self.assertEqual(INITIAL_SHA256, receipt['files']['data.store']['sha256'])
        self.assertTrue(receipt['data_preservation']['initial_sha256_preserved'])
        self.assertFalse(receipt['persistence_verified'])
        backups = list(self.base.glob('ios16-previous-*'))
        self.assertEqual(1, len(backups))
        self.assertEqual(self.marker, self.user_data(backups[0]))
        self.assertFalse((self.base / module.JOURNAL).exists()); self.check14()

    def test_same_size_corrupt_new_immutable_never_replaces_old(self):
        (self.stage / 'Image').write_bytes(b'BAD immutable bytes')
        with self.assertRaisesRegex(ValueError, 'SHA|hash'):
            module.promote(self.base, self.stage)
        self.assertEqual(b'old immutable bytes', (self.old / 'Image').read_bytes())
        self.assertEqual(self.marker, self.user_data(self.old)); self.check14()

    def test_damaged_old_immutable_is_repairable_without_resetting_valid_data(self):
        (self.old / 'Image').write_bytes(b'corrupt old')
        result = module.promote(self.base, self.stage)
        self.assertEqual(self.marker, self.user_data(result)); self.check14()

    def test_invalid_existing_data_format_refuses_fresh_reset(self):
        with (self.old / 'data.store').open('r+b') as stream: stream.write(b'INVALID')
        with self.assertRaisesRegex(ValueError, 'identity|layout'):
            module.promote(self.base, self.stage)
        with (self.old / 'data.store').open('rb') as stream: self.assertEqual(b'INVALID', stream.read(7))
        self.assertEqual(b'old immutable bytes', (self.old / 'Image').read_bytes()); self.check14()

    def test_missing_previously_recorded_data_refuses_silent_fresh_archive(self):
        (self.old / 'data.store').unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            module.promote(self.base, self.stage)
        self.assertEqual(b'old immutable bytes', (self.old / 'Image').read_bytes())

    def test_cancellation_before_and_after_journal_keeps_original(self):
        with self.assertRaises(InterruptedError):
            module.promote(self.base, self.stage, Hooks(cancelled=lambda: True))
        self.assertEqual(self.marker, self.user_data(self.old))
        cancelled = [False]
        def checkpoint(phase):
            if phase == 'journal_ready': cancelled[0] = True
        with self.assertRaises(InterruptedError):
            module.promote(self.base, self.stage, Hooks(cancelled=lambda: cancelled[0]), checkpoint)
        self.assertEqual(b'old immutable bytes', (self.old / 'Image').read_bytes())
        self.assertEqual(self.marker, self.user_data(self.old)); self.check14()

    def test_crash_before_rename_retains_old_and_retires_journal(self):
        def checkpoint(phase):
            if phase == 'journal_ready': raise Crash()
        with self.assertRaises(Crash): module.promote(self.base, self.stage, checkpoint=checkpoint)
        self.assertTrue((self.base / module.JOURNAL).exists())
        self.assertEqual(self.old, module.recover(self.base))
        self.assertEqual(b'old immutable bytes', (self.old / 'Image').read_bytes())
        self.assertEqual(self.marker, self.user_data(self.old)); self.check14()

    def test_crash_between_renames_restores_original(self):
        def checkpoint(phase):
            if phase == 'old_moved': raise Crash()
        with self.assertRaises(Crash): module.promote(self.base, self.stage, checkpoint=checkpoint)
        self.assertFalse(self.old.exists())
        self.assertEqual(self.old, module.recover(self.base))
        self.assertEqual(b'old immutable bytes', (self.old / 'Image').read_bytes())
        self.assertEqual(self.marker, self.user_data(self.old)); self.check14()

    def test_crash_after_new_rename_recognizes_verified_current(self):
        def checkpoint(phase):
            if phase == 'new_moved': raise Crash()
        with self.assertRaises(Crash): module.promote(self.base, self.stage, checkpoint=checkpoint)
        self.assertEqual(self.old, module.recover(self.base))
        self.assertEqual(b'new immutable bytes', (self.old / 'Image').read_bytes())
        self.assertEqual(self.marker, self.user_data(self.old)); self.check14()

    def test_corruption_after_crash_rolls_back_owned_candidate_and_keeps_evidence(self):
        def checkpoint(phase):
            if phase == 'new_moved': raise Crash()
        with self.assertRaises(Crash): module.promote(self.base, self.stage, checkpoint=checkpoint)
        (self.old / 'Image').write_bytes(b'broken')
        self.assertEqual(self.old, module.recover(self.base))
        self.assertEqual(b'old immutable bytes', (self.old / 'Image').read_bytes())
        self.assertTrue(list(self.base.glob('ios16-damaged-*')))
        self.assertEqual(self.marker, self.user_data(self.old)); self.check14()

    def test_stale_journal_cannot_overwrite_an_unrelated_current_directory(self):
        def checkpoint(phase):
            if phase == 'old_moved': raise Crash()
        with self.assertRaises(Crash): module.promote(self.base, self.stage, checkpoint=checkpoint)
        self.old.mkdir(); (self.old / 'unrelated').write_text('new user action')
        with self.assertRaisesRegex(ValueError, 'identity|unrelated'):
            module.recover(self.base)
        self.assertEqual('new user action', (self.old / 'unrelated').read_text())
        self.assertTrue((self.base / module.JOURNAL).exists()); self.check14()

    def test_malformed_or_traversing_journal_is_preserved_without_mutation(self):
        journal = self.base / module.JOURNAL
        journal.write_text(json.dumps({'profile': module.PROFILE, 'stage': '../ios-current'}))
        before = journal.read_bytes()
        with self.assertRaises(ValueError): module.recover(self.base)
        self.assertEqual(before, journal.read_bytes())
        self.assertEqual(self.marker, self.user_data(self.old)); self.check14()

    def test_preparation_lock_only_reclaims_demonstrably_dead_owner(self):
        prep = self.base / 'ios16-preparation'; prep.mkdir(exist_ok=True)
        lock = prep / '.ios16-preparation.lock'; lock.write_text(str(os.getpid()))
        with self.assertRaisesRegex(RuntimeError, 'active|owner'):
            module.reclaim_stale_preparation_lock(self.base)
        self.assertTrue(lock.exists())
        with patch.object(module, '_pid_alive', return_value=False):
            module.reclaim_stale_preparation_lock(self.base)
        self.assertFalse(lock.exists())
        lock.write_text('unrecognized owner')
        with self.assertRaises(ValueError): module.reclaim_stale_preparation_lock(self.base)
        self.assertTrue(lock.exists()); self.check14()

    def test_kernel_integration_lock_refuses_concurrent_owner(self):
        with module.integration_lock(self.base):
            with self.assertRaises(RuntimeError):
                with module.integration_lock(self.base): self.fail('nested owner')
        with module.integration_lock(self.base): pass

    def test_symbolic_prepared_path_is_rejected_before_touching_current(self):
        link = self.base / 'ios16-preparation/runs/preparation-link'
        try: link.symlink_to(self.stage.parent, target_is_directory=True)
        except OSError: self.skipTest('host cannot create symlink')
        with self.assertRaises(ValueError): module.promote(self.base, link / 'final')
        self.assertEqual(self.marker, self.user_data(self.old)); self.check14()

    def test_sparse_copy_fallback_preserves_nonzero_bytes_in_both_slots(self):
        with (self.old / 'data.store').open('r+b') as stream:
            stream.seek(STORE_BYTES - 8192); stream.write(b'late essential data')
        with patch.object(os, 'link', side_effect=OSError('no hard links')):
            result = module.promote(self.base, self.stage)
        self.assertEqual(self.marker, self.user_data(result))
        with (result / 'data.store').open('rb') as stream:
            stream.seek(STORE_BYTES - 8192); self.assertEqual(b'late essential data', stream.read(19))
        self.assertEqual('sparse_copy', json.loads((result / 'installation.json').read_text())['data_preservation']['method'])
        self.check14()

    def test_os_lock_survives_live_owner_and_is_released_after_process_death(self):
        code = ('import sys;from iosvm import installer16 as m;'
                'ctx=m.integration_lock(sys.argv[1]);ctx.__enter__();print("OWNED",flush=True);sys.stdin.read(1)')
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(self.base)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual('OWNED', child.stdout.readline().strip())
            with self.assertRaises(RuntimeError):
                with module.integration_lock(self.base): self.fail('Two process owners')
        finally:
            child.kill(); child.communicate(timeout=5)
        with module.integration_lock(self.base): pass

    def test_fresh_profile_promotion_has_empty_archive_and_unqualified_receipt(self):
        self.old.rename(self.base / 'unrelated-existing-directory')
        result = module.promote(self.base, self.stage)
        self.assertEqual(bytes(len(self.marker)), self.user_data(result))
        receipt = json.loads((result / 'installation.json').read_text())
        self.assertFalse(any(receipt[key] for key in ('gui_boot_verified', 'input_verified', 'persistence_verified')))
        self.check14()

    def test_adapter_calls_prepare_with_private_resources_and_java_style_hooks(self):
        resources = self.base / 'resources'; resources.mkdir()
        (resources / 'resource-manifest.json').write_text(json.dumps({'profile': module.PROFILE, 'persistence': True}))
        class Callback:
            def __init__(self): self.messages = []
            def isCancelled(self): return False
            def update(self, message, fraction): self.messages.append((message, fraction))
        callback = Callback()
        def prepare(base, manifest, asset_root, native_root, hooks):
            self.assertEqual(self.base / 'ios16-preparation', base)
            self.assertEqual(resources / 'assets', asset_root)
            hooks.report('synthetic prepare callback', .5)
            return self.stage
        result = module.install(self.base, self.base / 'native', resources, callback, prepare_fn=prepare)
        self.assertEqual(str(self.old), result)
        self.assertIn(('synthetic prepare callback', .5), callback.messages)
        self.assertEqual(self.marker, self.user_data(self.old)); self.check14()

    def test_sqlite_smoke_commits_and_reads_real_private_transaction(self):
        result = json.loads(module.sqlite_smoke(self.base))
        self.assertTrue(result['transaction_verified'])
        self.assertTrue(result['native_extension_loaded'])
        self.assertEqual(1, result['rows'])
        self.assertFalse(list(self.base.glob('ios16-sqlite-smoke-*')))
        self.check14()

    def test_typed_malformed_journal_is_rejected_without_rewriting_any_directory(self):
        (self.base / module.JOURNAL).write_text(json.dumps({'schema_version': 1,
            'profile': module.PROFILE, 'token': []}))
        with self.assertRaises(ValueError): module.recover(self.base)
        self.assertEqual(self.marker, self.user_data(self.old)); self.check14()

    def test_cancellation_after_old_rename_rolls_back_without_resetting_data(self):
        cancelled = [False]
        def checkpoint(phase):
            if phase == 'old_moved': cancelled[0] = True
        with self.assertRaises(InterruptedError):
            module.promote(self.base, self.stage, Hooks(cancelled=lambda: cancelled[0]), checkpoint)
        self.assertEqual(b'old immutable bytes', (self.old / 'Image').read_bytes())
        self.assertEqual(self.marker, self.user_data(self.old)); self.check14()

    def test_missing_old_receipt_preserves_archive_with_honest_snapshot_provenance(self):
        (self.old / 'installation.json').unlink()
        result = module.promote(self.base, self.stage)
        record = json.loads((result / 'installation.json').read_text())['files']['data.store']
        self.assertNotEqual(INITIAL_SHA256, record['sha256'])
        self.assertIn('creation provenance unavailable', record['sha256_origin'])
        self.assertEqual(self.marker, self.user_data(result)); self.check14()

    def test_failed_preparation_and_nonpersistent_manifest_do_not_touch_old_install(self):
        resources = self.base / 'resources'; resources.mkdir()
        manifest = resources / 'resource-manifest.json'
        manifest.write_text(json.dumps({'profile': module.PROFILE, 'persistence': True}))
        class Callback:
            def isCancelled(self): return False
            def update(self, message, fraction): pass
        def failed(*args): raise RuntimeError('synthetic extraction failed')
        with self.assertRaisesRegex(RuntimeError, 'extraction failed'):
            module.install(self.base, self.base / 'native', resources, Callback(), prepare_fn=failed)
        manifest.write_text(json.dumps({'profile': module.PROFILE, 'persistence': False}))
        with self.assertRaisesRegex(ValueError, 'persistent'):
            module.install(self.base, self.base / 'native', resources, Callback(), prepare_fn=failed)
        self.assertEqual(self.marker, self.user_data(self.old)); self.check14()


if __name__ == '__main__': unittest.main()
