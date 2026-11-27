"""Exercise actual boot activation and initramfs checks with update/failure cases."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import shlex
import re

ROOT = Path(__file__).resolve().parents[1]
BOOTCTL = ROOT/'scripts/bpi-m4-bootctl'
POLICY = ROOT/'src/initramfs/sd-root.bash'


def checksums(directory, names):
    (directory/'SHA256SUMS').write_text(''.join(
        hashlib.sha256((directory/name).read_bytes()).hexdigest()+'  '+name+'\n'
        for name in names))


class KernelUpdates(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.initrd = self.root/'usr/lib/bpi-m4/sd-boot'
        self.initrd.mkdir(parents=True)
        self.initrd_image(b'first generic runtime')
        self.first = '7.3.5-bpi_m4_fc_p10.r1.aaaaaaaaaaaa'
        self.second = '7.3.5-bpi_m4_fc_p10.r2.bbbbbbbbbbbb'

    def initrd_image(self, content):
        (self.initrd/'initramfs.img').write_bytes(gzip.compress(content, mtime=0))
        checksums(self.initrd, ['initramfs.img'])

    def kernel(self, release, profile=None):
        directory = self.root/'usr/lib/bpi-m4/kernels'/release
        directory.mkdir(parents=True)
        image = bytearray(64)
        image[56:60] = bytes.fromhex('41524d64')
        (directory/'Image').write_bytes(image+release.encode())
        (directory/'board.dtb').write_bytes(bytes.fromhex('d00dfeed')+b'test DTB')
        files = ['Image', 'board.dtb']
        if profile is not None:
            (directory/'boot-profile').write_text(profile+'\n')
            files.append('boot-profile')
        checksums(directory, files)
        (self.root/'usr/lib/modules'/release).mkdir(parents=True)
        return directory

    def media_packages(self):
        directory = self.root/'usr/lib/firmware/realtek/rtd1395'
        directory.mkdir(parents=True)
        (directory/'bluecore.audio').write_bytes(b'private firmware integrity fixture')
        checksums(directory, ['bluecore.audio'])
        for helper in ('bpi-m4-hdmi-start', 'bpi-m4-play', 'mpv'):
            path = self.root/'usr/bin'/helper
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('#!/bin/bash\nexit 0\n')
            path.chmod(0o755)

    def test_profiles_preserve_selection_across_updates_and_removal(self):
        media = '7.3.5-bpi_m4_fc_p14_media.r3.cccccccccccc'
        newer_media = '7.3.5-bpi_m4_fc_p14_media.r4.dddddddddddd'
        self.kernel(self.first, 'server')
        self.kernel(media, 'media')
        self.command('add', self.first)
        self.command('add', media)
        self.assertIn('DEFAULT '+self.first+'\n', self.menu)
        self.assertIn('bpi_m4_mode=media', self.menu)
        previous = self.menu
        self.command('set-mode', 'media', success=False)
        self.assertEqual(self.menu, previous)
        self.media_packages()
        self.command('set-mode', 'media')
        self.kernel(self.second, 'server')
        self.command('add', self.second)
        self.assertIn('DEFAULT '+media+'\n', self.menu)
        self.kernel(newer_media, 'media')
        self.command('add', newer_media)
        self.assertIn('DEFAULT '+newer_media+'\n', self.menu)
        self.command('set-mode', 'server')
        self.assertIn('DEFAULT '+self.second+'\n', self.menu)
        self.command('remove', self.first)
        previous = self.menu
        self.command('remove', self.second, success=False)
        self.assertEqual(self.menu, previous)
        self.command('set-mode', 'media')
        self.command('remove', newer_media)
        self.assertIn('DEFAULT '+media+'\n', self.menu)
        self.command('remove', media)
        self.assertIn('DEFAULT '+self.second+'\n', self.menu)

    def test_profile_and_firmware_corruption_preserve_boot_selection(self):
        media = '7.3.5-bpi_m4_fc_p14_media.r3.cccccccccccc'
        self.kernel(self.first)
        self.command('add', self.first)
        source = self.kernel(media, 'media')
        (source/'boot-profile').write_text('server\n')
        previous = self.menu
        self.command('add', media, success=False)
        self.assertEqual(self.menu, previous)
        (source/'boot-profile').write_text('media\n')
        self.command('add', media)
        previous = self.menu
        self.media_packages()
        firmware = self.root/'usr/lib/firmware/realtek/rtd1395/bluecore.audio'
        firmware.write_bytes(b'corrupted after packaging')
        self.command('set-mode', 'media', success=False)
        self.assertEqual(self.menu, previous)
        bundle = self.root/'boot/bpi-m4'/media
        (bundle/'boot-profile').write_text('server\n')
        self.command('verify', success=False)

    def command(self, *arguments, success=True):
        result = subprocess.run([BOOTCTL, '--root', self.root, *arguments],
                                capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout+result.stderr)
        return result

    @property
    def menu(self):
        return (self.root/'boot/extlinux/extlinux.conf').read_text()

    def test_update_fallback_removal_and_initrd_snapshot(self):
        self.kernel(self.first)
        self.command('add', self.first)
        original = (self.root/'boot/bpi-m4'/self.first/'initramfs.img').read_bytes()
        self.initrd_image(b'updated generic runtime')
        self.command('add', self.first)
        self.assertEqual((self.root/'boot/bpi-m4'/self.first/'initramfs.img').read_bytes(), original)
        self.kernel(self.second)
        self.command('add', self.second)
        self.assertIn('DEFAULT '+self.second+'\n', self.menu)
        self.assertEqual(self.menu.count('\nLABEL '), 2)
        self.assertIn('root=${bpi_root}', self.menu)
        self.assertIn('${bpi_sd_args}', self.menu)
        self.assertNotEqual((self.root/'boot/bpi-m4'/self.second/'initramfs.img').read_bytes(), original)
        self.command('verify')
        self.command('set-default', self.first)
        self.assertIn('DEFAULT '+self.first+'\n', self.menu)
        self.command('remove', self.second)
        self.assertNotIn(self.second, self.menu)
        self.assertFalse((self.root/'boot/bpi-m4'/self.second).exists())
        previous = self.menu
        self.command('remove', self.first, success=False)
        self.assertEqual(self.menu, previous)

    def test_invalid_update_preserves_previous_selection(self):
        self.kernel(self.first)
        self.command('add', self.first)
        previous = self.menu
        source = self.kernel(self.second)
        (source/'Image').write_bytes(b'changed after packaging')
        self.command('add', self.second, success=False)
        self.assertEqual(self.menu, previous)
        self.assertFalse((self.root/'boot/bpi-m4'/self.second).exists())
        checksums(source, ['Image', 'board.dtb'])
        self.command('add', self.second, success=False)
        self.assertEqual(self.menu, previous)

    def test_existing_configuration_and_symlinks_are_preserved(self):
        self.kernel(self.first)
        menu = self.root/'boot/extlinux/extlinux.conf'
        menu.parent.mkdir(parents=True)
        menu.write_text('DEFAULT operator-managed\n')
        self.command('add', self.first, success=False)
        self.assertEqual(menu.read_text(), 'DEFAULT operator-managed\n')
        menu.unlink()
        self.command('add', self.first)
        bundle = self.root/'boot/bpi-m4'/self.first
        (bundle/'Image').unlink()
        (bundle/'Image').symlink_to(self.root/'usr/lib/bpi-m4/kernels'/self.first/'Image')
        self.command('verify', success=False)

    def test_corrupt_fallback_and_bad_extra_args_block_activation(self):
        self.kernel(self.first)
        self.command('add', self.first)
        self.kernel(self.second)
        args = self.root/'etc/bpi-m4/kernel-args'
        args.parent.mkdir(parents=True)
        args.write_text('quiet\nLABEL injected\n')
        previous = self.menu
        self.command('add', self.second, success=False)
        self.assertEqual(self.menu, previous)
        args.write_text('quiet\n')
        self.command('add', self.second)
        self.assertIn(' quiet\n', self.menu)
        previous = self.menu
        (self.root/'boot/bpi-m4'/self.first/'initramfs.img').write_bytes(b'broken')
        self.command('set-default', self.first, success=False)
        self.assertEqual(self.menu, previous)

    def test_parallel_installations_keep_both_complete_entries(self):
        self.kernel(self.first)
        self.kernel(self.second)
        processes = [subprocess.Popen([BOOTCTL, '--root', self.root, 'add', release],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for release in (self.first, self.second)]
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stdout+stderr)
        self.command('verify')
        self.assertEqual(self.menu.count('\nLABEL '), 2)

    def test_initramfs_root_parser_and_detected_sd_policy(self):
        def parse(commandline):
            return subprocess.run(['bash', '-c', 'source "$1"; parse_root_partuuid',
                'policy', POLICY], input=commandline+'\n', capture_output=True, text=True)
        self.assertEqual(parse('console=ttyS0 root=PARTUUID=AB123456-02 rw').stdout, 'ab123456-02\n')
        self.assertEqual(parse('root=PARTUUID=12345678-1234-5678-9abc-def012345678').returncode, 0)
        for value in ('', 'root=/dev/sda2', 'root=UUID=1234',
                      'root=PARTUUID=12345678-02 root=PARTUUID=87654321-02',
                      'root=PARTUUID=../../outside'):
            self.assertNotEqual(parse(value).returncode, 0)
        sys = self.root/'sys'
        params = self.root/'params'
        params.mkdir()
        cid = '12345678abcdef011010202030304040'
        data = {'class/block/mmcblk2p3/start':'2048', 'class/block/mmcblk2p3/size':'8192',
                'class/block/mmcblk2/size':'16384', 'class/block/mmcblk2/device/cid':cid}
        for path, value in data.items():
            file = sys/path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(value+'\n')
        policy = {'scratch_start':'2048', 'scratch_sectors':'8192', 'read_capacity':'16384',
                  'scratch_cid':cid, 'read_cid':cid, 'write_enable':'Y',
                  'native_write':'Y', 'native_read':'Y'}
        def accepted():
            return subprocess.run(['bash', '-c',
                'source "$1"; verify_sd_policy "$2" "$3" mmcblk2p3 mmcblk2',
                'policy', POLICY, sys, params], capture_output=True).returncode == 0
        for key, value in policy.items(): (params/key).write_text(value+'\n')
        self.assertTrue(accepted())
        for key in policy:
            original = (params/key).read_text()
            (params/key).write_text('0\n')
            self.assertFalse(accepted(), key)
            (params/key).write_text(original)
        (sys/'class/block/mmcblk2p3/size').write_text('999999\n')
        self.assertFalse(accepted())

    def test_srpm_update_identity_installonly_and_native_build_dependencies(self):
        sources = self.root/'sources'
        sources.mkdir()
        for name, value in {'bpi-build-id':'0123456789ab', 'bpi-build-profile':'server',
                            'bpi-boot-mode':'spi', 'kernel-update-release':'2'}.items():
            (sources/name).write_text(value+'\n')
        command = ['rpmspec', '--target', 'aarch64', '--define', '_sourcedir '+str(sources), '-q']
        spec = ROOT/'packaging/bpi-m4-kernel.spec'
        provides = subprocess.check_output([*command, '--provides', spec], text=True)
        self.assertIn('installonlypkg(kernel)', provides)
        self.assertIn('kernel-uname-r = 7.3.5-bpi_m4_fc_p10.r2.0123456789ab', provides)
        native = subprocess.check_output([*command, '--without', 'cross', '--buildrequires', spec], text=True)
        self.assertNotIn('gcc-aarch64-linux-gnu', native)
        cross = subprocess.check_output([*command, '--with', 'cross', '--buildrequires', spec], text=True)
        self.assertIn('gcc-aarch64-linux-gnu', cross)
        (sources/'bpi-build-profile').write_text('media\n')
        media = subprocess.check_output([*command, '--provides', spec], text=True)
        self.assertIn('kernel-uname-r = 7.3.5-bpi_m4_fc_p14_media.r2.0123456789ab', media)
        self.assertIn('bpi-m4-kernel-mode(media)', media)
        conflicts = subprocess.check_output([*command, '--conflicts', spec], text=True)
        self.assertEqual(conflicts, '')
        meta = subprocess.check_output([*command, '--requires',
            ROOT/'packaging/bpi-m4-board-support.spec'], text=True)
        self.assertIn('bpi-m4-kernel-mode(media)', meta)



    def test_rpm_install_and_erase_execute_the_kernel_hooks(self):
        # Build small lifecycle fixtures in Mock, using the real parsed kernel
        # scriptlets. Redirect only the helper's root to this private directory.
        sources = self.root/'sources'
        sources.mkdir()
        top = self.root/'rpmbuild'
        for directory in ('BUILD', 'BUILDROOT', 'RPMS', 'SOURCES', 'SPECS', 'SRPMS'):
            (top/directory).mkdir(parents=True)
        database = self.root/'rpmdb'
        rpm = ['rpm', '--dbpath', str(database), '--noplugins', '--nocontexts',
               '--nosignature', '--nodeps']
        result = subprocess.run(['rpm', '--dbpath', str(database), '--initdb'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        fixture_image = self.root/'fixture.Image'
        image = bytearray(64)
        image[56:60] = bytes.fromhex('41524d64')
        fixture_image.write_bytes(image)
        fixture_dtb = self.root/'fixture.dtb'
        fixture_dtb.write_bytes(bytes.fromhex('d00dfeed')+b'lifecycle fixture')
        releases = []
        for revision in (1, 2):
            for name, value in {'bpi-build-id':'0123456789ab', 'bpi-build-profile':'server',
                                'bpi-boot-mode':'spi', 'kernel-update-release':str(revision)}.items():
                (sources/name).write_text(value+'\n')
            parsed = subprocess.check_output(['rpmspec', '--target', 'aarch64',
                '--define', '_sourcedir '+str(sources), '--parse',
                ROOT/'packaging/bpi-m4-kernel.spec'], text=True)
            hooks = parsed[parsed.index('\n%post -p /bin/bash\n'):]
            hooks = hooks.replace('/usr/sbin/bpi-m4-bootctl',
                shlex.quote(str(BOOTCTL))+' --root '+shlex.quote(str(self.root)))
            hooks = hooks.replace('/run/bpi-m4-kernel-updates',
                str(self.root/'run/bpi-m4-kernel-updates'))
            release = '7.3.5-bpi_m4_fc_p10.r'+str(revision)+'.0123456789ab'
            releases.append(release)
            dest = str(self.root/'usr/lib/bpi-m4/kernels'/release)
            modules = str(self.root/'usr/lib/modules'/release)
            # Use the real SPEC's paths and different contents in each build:
            # shared documentation paths would break kernel co-installation.
            doc = str(self.root)+re.search(r'^%doc (/.*)$', parsed, re.M)[1]
            license_dir = str(self.root)+re.search(r'^%license (/.*)$', parsed, re.M)[1]
            spec = top/'SPECS/fixture.spec'
            spec.write_text(f'''Name: bpi-m4-hook-test
Version: 7.3.5
Release: {revision}
Summary: Private kernel RPM scriptlet fixture
License: GPL-2.0-or-later
Provides: kernel-uname-r = {release}
AutoReqProv: no
%global debug_package %{{nil}}
%description
Tests installation/removal hooks; not a bootable kernel.
%install
mkdir -p "%{{buildroot}}{dest}" "%{{buildroot}}{modules}" "%{{buildroot}}{doc}" "%{{buildroot}}{license_dir}"
cp {shlex.quote(str(fixture_image))} "%{{buildroot}}{dest}/Image"
cp {shlex.quote(str(fixture_dtb))} "%{{buildroot}}{dest}/board.dtb"
touch "%{{buildroot}}{modules}/fixture"
printf '%s\\n' '{release}' >"%{{buildroot}}{doc}/provenance.json"
printf '%s\\n' '{release}' >"%{{buildroot}}{license_dir}/COPYING"
(cd "%{{buildroot}}{dest}"; sha256sum Image board.dtb >SHA256SUMS)
%files
{dest}
{modules}
%doc {doc}
%license {license_dir}
''' + hooks)
            result = subprocess.run(['rpmbuild', '--define', '_topdir '+str(top), '-bb', spec],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            product = next((top/'RPMS').rglob(f'bpi-m4-hook-test-7.3.5-{revision}.*.rpm'))
            result = subprocess.run([*rpm, '-i', product], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('DEFAULT '+release+'\n', self.menu)
        self.assertEqual(self.menu.count('\nLABEL '), 2)
        result = subprocess.run([*rpm, '--reinstall', product], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(self.menu.count('\nLABEL '), 2)
        result = subprocess.run([*rpm, '-e', 'bpi-m4-hook-test-7.3.5-1'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertNotIn(releases[0], self.menu)
        result = subprocess.run([*rpm, '-e', 'bpi-m4-hook-test-7.3.5-2'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('last bootable entry', result.stderr)
        self.assertIn('DEFAULT '+releases[1]+'\n', self.menu)
        self.assertEqual(subprocess.run(['rpm', '--dbpath', str(database), '-q',
                         'bpi-m4-hook-test'], capture_output=True).returncode, 0)
