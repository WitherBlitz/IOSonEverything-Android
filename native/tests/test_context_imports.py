import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location('context_imports', Path(__file__).parents[1] / 'context_imports.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def elf_fixture():
    image = bytearray(512)
    image[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', image, 18, 183)
    struct.pack_into('<Q', image, 40, 64)
    struct.pack_into('<HH', image, 58, 64, 3)
    # dynsym section links to string table; two imported function symbols.
    struct.pack_into('<IIQQQQIIQQ', image, 128, 0, 11, 0, 0, 256, 72, 2, 0, 8, 24)
    strings = b'\0sigsetjmp\0siglongjmp\0'
    struct.pack_into('<IIQQQQIIQQ', image, 192, 0, 3, 0, 0, 352, len(strings), 0, 0, 1, 0)
    struct.pack_into('<IBBHQQ', image, 280, 1, 18, 0, 0, 0, 0)
    struct.pack_into('<IBBHQQ', image, 304, 11, 18, 0, 0, 0, 0)
    image[352:352 + len(strings)] = strings
    return bytes(image)


class ContextImports(unittest.TestCase):
    def test_only_import_name_bytes_change_and_size_is_preserved(self):
        original = elf_fixture()
        changed = module.rename_imports(original)
        self.assertEqual(len(changed), len(original))
        self.assertEqual(changed[:352], original[:352])
        self.assertIn(b'\0iossetjmp\0ioslongjmp\0', changed)
        self.assertEqual(changed[374:], original[374:])

    def test_missing_or_already_changed_symbols_are_rejected(self):
        with self.assertRaises(ValueError):
            module.rename_imports(module.rename_imports(elf_fixture()))

    def test_exported_symbols_are_rejected(self):
        image = bytearray(elf_fixture())
        struct.pack_into('<H', image, 286, 1)
        with self.assertRaises(ValueError):
            module.rename_imports(bytes(image))

    def test_wrong_architecture_is_rejected(self):
        image = bytearray(elf_fixture())
        struct.pack_into('<H', image, 18, 62)
        with self.assertRaises(ValueError):
            module.rename_imports(bytes(image))


if __name__ == '__main__':
    unittest.main()
