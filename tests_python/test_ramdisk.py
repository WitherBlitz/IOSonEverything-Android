import io
import struct
import unittest
import pathlib
import plistlib
import tempfile
from unittest.mock import patch
from iosvm.ramdisk import Volume
from iosvm import ramdisk


def volume_fixture(compressed=False):
    data = bytearray(16 * 512)
    data[1024:1026] = b'HX'
    struct.pack_into('>III', data, 1024 + 40, 512, 16, 4)
    for offset, start, count in [(112, 3, 1), (272, 4, 4)]:
        struct.pack_into('>QII', data, 1024 + offset, count * 512, 0, count)
        struct.pack_into('>II', data, 1024 + offset + 16, start, count)
    data[3 * 512:3 * 512 + 2] = b'\xff\xf0'
    struct.pack_into('>I', data, 4 * 512 + 24, 1)
    struct.pack_into('>H', data, 4 * 512 + 32, 512)
    leaf = 5 * 512
    struct.pack_into('>H', data, leaf + 10, 1)
    struct.pack_into('>H', data, leaf + 510, 14)
    struct.pack_into('>HIH', data, leaf + 14, 12, 2, 3)
    data[leaf + 22:leaf + 28] = 'job'.encode('utf-16-be')
    record = leaf + 28
    struct.pack_into('>H', data, record, 2)
    struct.pack_into('>I', data, record + 8, 17)
    if compressed:
        data[record + 41] = 0x20
    else:
        struct.pack_into('>Q', data, record + 88, 8)
        struct.pack_into('>I', data, record + 100, 1)
        struct.pack_into('>II', data, record + 104, 10, 1)
        data[10 * 512:10 * 512 + 8] = b'ORIGINAL'
    return io.BytesIO(data), record


class RamdiskTests(unittest.TestCase):
    def test_patch_boot_carries_sep_firmware_without_starting_unsynchronized_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            stock, destination, daemon, patcher, sep = [root / name for name in
                                                       ('stock', 'patched', 'daemon', 'patcher', 'sep')]
            stock.write_bytes(b'original ramdisk')
            daemon.write_bytes(b'\xcf\xfa\xed\xfe' + b'daemon')
            patcher.write_bytes(b'\xcf\xfa\xed\xfe' + b'patcher')
            sep.write_bytes(b'prepared firmware')
            with patch.object(ramdisk, 'Volume') as volume, patch.object(ramdisk, 'payload_offset', return_value=0):
                ramdisk.patch_ramdisk(stock, destination, daemon, patcher, sep)
            writes = {args[0]: args[1] for args, _ in volume.return_value.replace.call_args_list}
            job = plistlib.loads(writes[ramdisk.RESTORED_JOB])
            self.assertTrue(job['Disabled'])
            self.assertEqual(job['ProgramArguments'], ['/usr/local/bin/restored_external'])
            self.assertEqual(writes[ramdisk.SEP_PAYLOAD], sep.read_bytes())
            self.assertEqual(stock.read_bytes(), b'original ramdisk')

    def test_replacement_preserves_file_allocation_and_updates_catalog_length(self):
        image, record = volume_fixture()
        volume = Volume(image, 0)
        volume.replace('/job', b'NEW', 0o755)
        self.assertEqual(image.getvalue()[10 * 512:10 * 512 + 8], b'NEWGINAL')
        self.assertEqual(struct.unpack_from('>Q', image.getvalue(), record + 88)[0], 3)
        self.assertEqual(struct.unpack_from('>H', image.getvalue(), record + 42)[0], 0o100755)

    def test_compressed_job_gets_free_block_and_loses_compressed_flag(self):
        image, record = volume_fixture(True)
        volume = Volume(image, 0)
        volume.replace('/job', b'PLIST', 0o644)
        self.assertEqual(image.getvalue()[12 * 512:12 * 512 + 5], b'PLIST')
        self.assertEqual(image.getvalue()[3 * 512 + 1], 0xf8)
        self.assertEqual(image.getvalue()[record + 41], 0)
        self.assertEqual(struct.unpack_from('>I', image.getvalue(), 1024 + 48)[0], 3)

    def test_missing_path_fails_without_modifying_image(self):
        image, _ = volume_fixture()
        before = image.getvalue()
        with self.assertRaisesRegex(ValueError, 'Missing'):
            Volume(image, 0).replace('/unknown', b'bad', 0o644)
        self.assertEqual(image.getvalue(), before)
