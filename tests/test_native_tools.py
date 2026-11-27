import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from bpi_image.initramfs import runtime_command

class NativeRuntimeTests(TestCase):
    def test_native_executes_staged_loader_without_chroot(self):
        with tempfile.TemporaryDirectory() as t:
            stage=Path(t)
            (stage/'lib').mkdir();(stage/'bin').mkdir()
            (stage/'lib/ld-linux-aarch64.so.1').touch();(stage/'bin/bash').touch()
            with patch('bpi_image.initramfs.platform.machine',return_value='aarch64'):
                command=runtime_command(stage,'/bin/bash')
            self.assertEqual(command[0],stage/'lib/ld-linux-aarch64.so.1')
            self.assertIn('--library-path',command)
            self.assertEqual(command[-1],stage/'bin/bash')
    def test_cross_executes_arm_runtime_under_qemu(self):
        with patch('bpi_image.initramfs.platform.machine',return_value='x86_64'):
            command=runtime_command(Path('/stage'),'/bin/bash')
        self.assertEqual(command,['qemu-aarch64-static','-L',Path('/stage'),Path('/stage/bin/bash')])
