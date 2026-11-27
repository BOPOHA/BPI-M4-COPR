"""Verify Git source selection and source-only build identities."""
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from bpi_packaging.common import ROOT
from bpi_packaging.copr_source import selection
from bpi_packaging.rpm_packages import build_environment, recipe_files


class CoprSourceTests(TestCase):
    def test_server_and_media_select_the_update_recipe(self):
        self.assertEqual(selection('packaging/bpi-m4-kernel.spec'),
                         ('kernel-updates', 'server', 'kernel-updates'))
        self.assertEqual(selection(ROOT/'packaging/bpi-m4-kernel-media.spec'),
                         ('kernel-updates', 'media', 'kernel-media-updates'))

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
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                selection(spec)

    def test_source_identity_needs_no_mock_or_host_rpm_queries(self):
        with patch.dict(os.environ, {'BPI_COPR_SOURCE': '1'}), \
                patch('bpi_packaging.rpm_packages.run', side_effect=AssertionError('host query')):
            self.assertEqual(build_environment(), {'mode': 'copr-scm', 'format': 1})
            files = recipe_files('packaging/bpi-m4-kernel.spec')
            self.assertIn(ROOT/'.copr/Makefile', files)
            self.assertIn(ROOT/'bpi_packaging/copr_source.py', files)
            self.assertIn(ROOT/'packaging/keys/RPM-GPG-KEY-fedora-45-primary', files)
