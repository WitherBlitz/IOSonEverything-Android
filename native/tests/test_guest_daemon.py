import hashlib
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adapt_guest_daemon import adapt, code_directory, verify_code_hashes, ORIGINAL_SHA256


class GuestDaemonAdaptationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = (Path(__file__).resolve().parents[2] /
                        'third_party/guest-tools-source/original-inferno_patcher').read_bytes()

    def test_adaptation_preserves_layout_and_has_valid_adhoc_code_hashes(self):
        output = adapt(self.original)
        self.assertEqual(len(output), len(self.original))
        verify_code_hashes(self.original)
        verify_code_hashes(output)
        self.assertEqual(output[0x495f:0x4964], b'.\0\0\0\0')
        self.assertEqual(output[0x45d0:0x4650], self.original[0x45d0:0x4650])
        # The existing execv call now branches to the bounded in-segment trace.
        word = struct.unpack_from('<I', output, 0x45cc)[0]
        displacement = word & 0x3ffffff
        if displacement & 0x2000000: displacement -= 0x4000000
        self.assertEqual(0x45cc + displacement * 4, 0x1000)
        self.assertEqual(hashlib.sha256(self.original).hexdigest(), ORIGINAL_SHA256)

    def test_trace_branches_addresses_and_changed_byte_ranges(self):
        output = adapt(self.original)
        for source, target, linked in ((0x45cc, 0x1000, False),
                                       (0x40cc, 0x1200, True),
                                       (0x458c, 0x12e0, False),
                                       (0x1018, 0x4710, True),
                                       (0x1020, 0x46c0, True),
                                       (0x1030, 0x1700, False)):
            word = struct.unpack_from('<I', output, source)[0]
            self.assertEqual(word & 0xfc000000, 0x94000000 if linked else 0x14000000)
            displacement = word & 0x3ffffff
            if displacement & 0x2000000:
                displacement -= 0x4000000
            self.assertEqual(source + displacement * 4, target)
        for source, target, register in ((0x1014, 0x1080, 0), (0x102c, 0x45d0, 30)):
            word = struct.unpack_from('<I', output, source)[0]
            self.assertEqual(word & 0x9f000000, 0x10000000)
            self.assertEqual(word & 31, register)
            displacement = (((word >> 5) & 0x7ffff) << 2) | ((word >> 29) & 3)
            if displacement & 0x100000:
                displacement -= 0x200000
            self.assertEqual(source + displacement, target)
        hashes, _, _ = code_directory(output)
        allowed = ((0x1000, 0x1034), (0x1080, 0x109d), (0x1200, 0x1900),
                   (0x40cc, 0x40d0), (0x458c, 0x4590), (0x45cc, 0x45d0),
                   (0x495f, 0x4964), (hashes + 32, hashes + 64),
                   (hashes + 4 * 32, hashes + 5 * 32))
        for offset, (old, new) in enumerate(zip(self.original, output)):
            if old != new:
                self.assertTrue(any(start <= offset < end for start, end in allowed),
                                'unexpected changed byte at %#x' % offset)

    def test_other_build_is_rejected_before_modification(self):
        changed = bytearray(self.original); changed[0x4000] ^= 1
        with self.assertRaisesRegex(ValueError, 'SHA'):
            adapt(bytes(changed))

    def test_code_signature_verification_detects_changed_page(self):
        changed = bytearray(adapt(self.original)); changed[0x1000] ^= 1
        with self.assertRaisesRegex(ValueError, 'hash'):
            verify_code_hashes(changed)
