"""Regression: the target loader may live in /usr/lib, despite lib64 ELF users."""
from pathlib import Path
from tempfile import TemporaryDirectory
import struct
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from bpi_packaging.initramfs import closure, copy_target

class InitramfsClosureTest(unittest.TestCase):
    def test_loader_directory_and_soname_are_preserved(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)/'root'
            stage = Path(directory)/'stage'
            (root/'usr/lib64').mkdir(parents=True)
            (root/'usr/lib').mkdir()
            elf = bytearray(64)
            elf[:6] = b'\x7fELF\x02\x01'
            struct.pack_into('<H', elf, 18, 183)
            (root/'usr/lib64/libc.so.6').write_bytes(elf)
            (root/'usr/lib64/libtransitive.so.1').write_bytes(elf)
            (root/'usr/lib/ld-linux-aarch64.so.1').write_bytes(elf)
            (root/'lib').symlink_to('usr/lib')
            def headers(args, **kwargs):
                text = ''
                if str(args[-1]).endswith('/libc.so.6'):
                    text = '(NEEDED) Shared library: [ld-linux-aarch64.so.1]\n'
                if str(args[-1]).endswith('/ld-linux-aarch64.so.1'):
                    text = '(NEEDED) Shared library: [libtransitive.so.1]\n'
                return SimpleNamespace(stdout=text)
            with patch('bpi_packaging.initramfs.run', side_effect=headers):
                files = closure(root, ['/usr/lib64/libc.so.6'])
            self.assertIn('/usr/lib/ld-linux-aarch64.so.1', files)
            self.assertIn('/usr/lib64/libtransitive.so.1', files)
            self.assertNotIn('/usr/lib64/ld-linux-aarch64.so.1', files)
            for name in files:
                copy_target(root, stage, name)
            self.assertEqual((stage/'usr/lib/ld-linux-aarch64.so.1').read_bytes(), elf)

if __name__ == '__main__':
    unittest.main()
