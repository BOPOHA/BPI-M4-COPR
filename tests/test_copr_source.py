"""Verify Git source selection and source-only build identities."""
import os
import json
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from bpi_packaging.common import ROOT, FEDORA_FPR, verify_key
from bpi_packaging.rpm_packages import build_environment, recipe_files


def selection(spec):
    result = subprocess.run([ROOT/'scripts/copr-srpm.bash', '--spec', str(spec), '--describe'],
                            cwd=ROOT, check=True, capture_output=True, text=True)
    entry = json.loads(result.stdout)
    return entry['component'], entry['profile'], entry['alias']


class CoprSourceTests(TestCase):
    def test_server_and_media_select_the_update_recipe(self):
        self.assertEqual(selection('packaging/bpi-m4-kernel.spec'),
                         ('kernel', 'server', 'kernel'))
        self.assertEqual(selection(ROOT/'packaging/bpi-m4-kernel-media.spec'),
                         ('kernel', 'media', 'kernel-media'))

    def test_non_kernel_packages_select_one_srpm(self):
        for spec, alias in [('board-support', 'board'), ('sd-boot', 'sd-boot'),
                            ('native-codecs', 'codecs'), ('build-checks', 'checks'),
                            ('module-checks', 'module-checks')]:
            with self.subTest(spec=spec):
                self.assertEqual(selection('packaging/bpi-m4-'+spec+'.spec')[2], alias)

    def test_firmware_unknown_and_external_specs_are_rejected(self):
        for spec in ['packaging/bpi-m4-media-firmware.spec',
                     'packaging/missing.spec', '/tmp/bpi-m4-kernel.spec',
                     'packaging/../README.md']:
            with self.subTest(spec=spec), self.assertRaises(subprocess.CalledProcessError):
                selection(spec)

    def test_source_identity_needs_no_mock_or_host_rpm_queries(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch('bpi_packaging.rpm_packages.run', side_effect=AssertionError('host query')):
            self.assertEqual(build_environment(), {'mode': 'copr-scm', 'format': 1})
            files = recipe_files('packaging/bpi-m4-kernel.spec')
            self.assertIn(ROOT/'.copr/Makefile', files)
            self.assertIn(ROOT/'scripts/copr-srpm.bash', files)
            self.assertIn(ROOT/'packaging/keys/RPM-GPG-KEY-fedora-45-primary', files)

    def test_key_verification_ignores_missing_user_gnupg_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary)/'absent-keyring'
            with patch.dict(os.environ, {'GNUPGHOME': str(missing)}):
                key = ROOT/'packaging/keys/RPM-GPG-KEY-fedora-45-primary'
                verify_key(key, FEDORA_FPR)
                with self.assertRaises(ValueError):
                    verify_key(key, '0'*40)
            self.assertFalse(missing.exists())
