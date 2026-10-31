import copy
import io
import plistlib
import unittest
import zipfile

from iosvm.firmware import select_identity, stored_range, personalize, decrypt_sep


class FirmwareTests(unittest.TestCase):
    def manifest(self):
        return {"ProductBuildVersion": "18A5351d", "SupportedProductTypes": ["iPhone12,1"],
                "BuildIdentities": [{"Info": {"DeviceClass": "n104ap", "RestoreBehavior": "Erase",
                                              "Variant": "Developer Erase Install (IPSW)"},
                                     "Manifest": {"KernelCache": {"Info": {"Path": "kernel"}}}}]}

    def test_rejects_wrong_build_before_preparing_components(self):
        m = self.manifest()
        m["ProductBuildVersion"] = "18H17"
        with self.assertRaisesRegex(ValueError, "build"):
            select_identity(m)

    def test_production_erase_identity_excludes_research_and_upgrade(self):
        m = self.manifest()
        research = copy.deepcopy(m["BuildIdentities"][0])
        research["Info"]["Variant"] = "Research Developer Erase Install (IPSW)"
        upgrade = copy.deepcopy(m["BuildIdentities"][0])
        upgrade["Info"]["RestoreBehavior"] = "Update"
        m["BuildIdentities"] = [research, upgrade] + m["BuildIdentities"]
        self.assertEqual(select_identity(m)["Info"]["Variant"], "Developer Erase Install (IPSW)")

    def test_rejects_ambiguous_identity_instead_of_guessing(self):
        m = self.manifest()
        m["BuildIdentities"] *= 2
        with self.assertRaisesRegex(ValueError, "identity"):
            select_identity(m)

    def test_stored_image_range_points_to_payload_after_variable_zip_header(self):
        f = io.BytesIO()
        with zipfile.ZipFile(f, "w") as z:
            info = zipfile.ZipInfo("system.dmg")
            info.extra = b"\x01\x00\x00\x00"
            z.writestr(info, b"independent system bytes")
        f.seek(0)
        with zipfile.ZipFile(f) as z:
            offset, size = stored_range(z, "system.dmg")
        self.assertEqual(size, 24)
        self.assertEqual(f.getvalue()[offset:offset + size], b"independent system bytes")

    def test_rejects_compressed_system_image_for_random_access_asr(self):
        f = io.BytesIO()
        with zipfile.ZipFile(f, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("system.dmg", b"payload")
        f.seek(0)
        with zipfile.ZipFile(f) as z, self.assertRaisesRegex(ValueError, "stored"):
            stored_range(z, "system.dmg")

    def test_personalization_preserves_im4p_and_wraps_ticket_explicitly(self):
        # Hand-encoded DER: IM4P/krnl/none, one byte of payload; IM4M ticket.
        raw = bytes.fromhex("30151604494d345016046b726e6c16046e6f6e650401aa")
        ticket = bytes.fromhex("30061604494d344d")
        expected = bytes.fromhex("30271604494d473430151604494d345016046b726e6c16046e6f6e650401aaa00830061604494d344d")
        self.assertEqual(personalize(raw, ticket), expected)

    def test_sep_decryption_matches_nist_aes256_cbc_vector_without_unpadding(self):
        key = bytes.fromhex("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4")
        iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        cipher = bytes.fromhex("f58c4c04d6e5f1ba779eabfb5f7bfbd6")
        self.assertEqual(decrypt_sep(cipher, iv, key), bytes.fromhex("6bc1bee22e409f96e93d7e117393172a"))


if __name__ == "__main__":
    unittest.main()
