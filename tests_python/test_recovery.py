import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from iosvm.acquisition import recover_installation, cleanup_staging, promote


def completed(path):
    path.mkdir()
    names = ('root', 'kernel', 'dtb', 'trustcache', 'sep_rom', 'sep_fw', 'vm.properties',
             'firmware', 'syscfg', 'ctrl_bits', 'nvram', 'effaceable', 'panic_log', 'sep_nvram', 'sep_ssc')
    for name in names:
        (path / name).write_bytes(b'valid guest data')
    (path / 'installation.json').write_text(json.dumps({'profile': 'iphone11-18A5351d-cpu-v1',
        'restored': True, 'patched': True, 'files': {name: 16 for name in names},
        'static_sha256': {name: hashlib.sha256(b'valid guest data').hexdigest()
                          for name in ('kernel', 'dtb', 'trustcache', 'sep_rom', 'sep_fw')}}))


class RecoveryTests(unittest.TestCase):
    def test_receipt_missing_boot_hash_cannot_replace_previous_usable_install(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            completed(base / 'ios-current')
            stage = base / 'ios-staging-123'; completed(stage)
            receipt = json.loads((stage / 'installation.json').read_text())
            del receipt['static_sha256']['kernel']
            (stage / 'installation.json').write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, 'hash'):
                promote(stage, base / 'ios-current')
            self.assertEqual((base / 'ios-current/kernel').read_bytes(), b'valid guest data')
            self.assertFalse((base / 'ios-current.previous').exists())

    def test_same_size_corrupt_boot_file_is_not_recovered_as_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            stage = base / 'ios-staging-123'; completed(stage)
            (stage / 'kernel').write_bytes(b'broken boot data')
            self.assertIsNone(recover_installation(base))
            self.assertFalse((base / 'ios-current').exists())

    def test_death_between_renames_restores_previous_working_guest(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            completed(base / 'ios-current.previous')
            current = recover_installation(base)
            self.assertEqual(current, base / 'ios-current')
            self.assertEqual((current / 'root').read_bytes(), b'valid guest data')

    def test_completed_stage_recovers_after_death_before_promotion(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            completed(base / 'ios-staging-123')
            self.assertEqual(recover_installation(base), base / 'ios-current')

    def test_cleanup_reclaims_only_abandoned_private_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            failed = base / 'ios-staging-124'; failed.mkdir(); (failed / 'root').write_bytes(b'partial')
            completed(base / 'ios-staging-125')
            unrelated = base / 'user-files'; unrelated.mkdir()
            cleanup_staging(base)
            self.assertFalse(failed.exists())
            self.assertTrue((base / 'ios-staging-125/root').is_file())
            self.assertTrue(unrelated.is_dir())
