"""Prepare self-contained source RPMs for the COPR Git source worker."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

from .common import ROOT, fetch, run, sha, verify_rpm, write_json
from .inputs import fedora_key_input, linux_key_input, verify_linux

SPECS = ROOT/'packaging'
WORK = ROOT/'work/rpms'
RPKG_CONFIG = SPECS/'rpkg.conf'


def build_environment():
    return {'mode': 'copr-scm', 'format': 1}


def identity(inputs, files):
    value = {'inputs':inputs, 'recipes':{str(p.relative_to(ROOT)):sha(p) for p in sorted(set(files))}}
    value['rpm_build'] = build_environment()
    return value


def recipe_files(*paths):
    files = [Path(__file__), ROOT/'bpi_packaging/common.py', ROOT/'bpi_packaging/inputs.py', ROOT/'scripts/clean-rpm-work.bash', ROOT/'scripts/build-srpm.bash', RPKG_CONFIG]
    files.extend([ROOT/'.copr/Makefile', ROOT/'scripts/copr-srpm.bash', ROOT/'packaging/copr-scm.json',
                  ROOT/'packaging/keys/RPM-GPG-KEY-fedora-45-primary'])
    for name in paths:
        path = ROOT/name
        files.extend(p for p in path.rglob('*') if p.is_file() and '__pycache__' not in p.parts) if path.is_dir() else files.append(path)
    return files


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def tar_tree(source, destination):
    """Deterministic source archive; preserve symlinks without following them."""
    def normalize(info):
        info.uid = info.gid = info.mtime = 0
        info.uname = info.gname = ''
        return info
    with destination.open('wb') as output, gzip.GzipFile(filename='', fileobj=output, mode='wb', compresslevel=1, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for path in [source, *sorted(source.rglob('*'))]:
                archive.add(path, arcname=str(path.relative_to(source.parent)), recursive=False, filter=normalize)


def fresh_workspace(name):
    work = WORK/name
    run([ROOT/'scripts/clean-rpm-work.bash', work])
    for directory in ('SOURCES', 'srpm-result'):
        (work/directory).mkdir(parents=True, exist_ok=True)
    return work


def copy_file(source, tree, relative):
    path = tree/relative
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, path)


def publish_product(product, output, alias_name):
    output.mkdir(parents=True, exist_ok=True)
    target = output/product.name
    temporary = target.with_suffix('.rpm.partial')
    shutil.copy2(product, temporary)
    temporary.replace(target)
    nevra, package_name = run(['rpm', '-qp', '--qf', '%{NEVRA}\t%{NAME}', target], capture=True).stdout.split('\t')
    alias = output/alias_name
    link = alias.with_suffix(alias.suffix+'.partial')
    link.unlink(missing_ok=True)
    link.symlink_to(target.name)
    link.replace(alias)
    item = {'path':str(target.relative_to(ROOT)), 'sha256':sha(target), 'nevra':nevra,
            'name':package_name, 'alias':str(alias.relative_to(ROOT))}
    target.with_suffix('.rpm.sha256').write_text(item['sha256']+'  '+target.name+'\n')
    return item


def srpm_build(name, work, spec_name, expected, metadata=None, version=''):
    print('rpkg srpm '+name+'; log '+str(work/'srpm.log'), flush=True)
    run([ROOT/'scripts/build-srpm.bash', RPKG_CONFIG, SPECS/spec_name, work,
         fingerprint(expected)[:12], expected['inputs'].get('profile', 'server'), version])
    sources = sorted((work/'srpm-result').glob('*.src.rpm'))
    if len(sources) != 1: raise ValueError('rpkg must produce exactly one SRPM')
    record = {'schema':1, 'identity':expected, 'srpms':[
        publish_product(sources[0], ROOT/'out/srpms', name+'.src.rpm')],
        'metadata':metadata or {}}
    write_json(ROOT/'out/srpms'/(name+'.json'), record)
    return record


def prepare_board():
    name = 'board'
    files = recipe_files('packaging/bpi-m4-board-support.spec', 'packaging/files',
        'scripts/bpi-m4-hdmi-start', 'docs/FIRST-BOOT.md',
        'docs/MEDIA-FIRMWARE.md', 'licenses/GPL-2.0.txt')
    expected = identity({}, files)
    work = fresh_workspace(name)
    tree = work/'prepared/bpi-m4-board-support'
    payload = tree/'payload'
    for source, dest in (
        ('packaging/files/10-bpi-m4.conf', 'etc/ssh/sshd_config.d/10-bpi-m4.conf'),
        ('packaging/files/bpi-m4-peripherals.conf', 'etc/modprobe.d/bpi-m4-peripherals.conf'),
        ('packaging/files/bpi-m4-media.conf', 'etc/modprobe.d/bpi-m4-media.conf'),
        ('scripts/bpi-m4-hdmi-start', 'usr/bin/bpi-m4-hdmi-start'),
        ('docs/FIRST-BOOT.md', 'usr/share/doc/bpi-m4/first-boot.md'),
        ('docs/MEDIA-FIRMWARE.md', 'usr/share/doc/bpi-m4/media-firmware.md'),
        ('licenses/GPL-2.0.txt', 'usr/share/licenses/bpi-m4-board-support/COPYING')):
        copy_file(ROOT/source, payload, dest)
    write_json(payload/'usr/share/doc/bpi-m4/provenance.json', expected)
    tar_tree(tree, work/'SOURCES/bpi-m4-board-support.tar.gz')
    return srpm_build(name, work, 'bpi-m4-board-support.spec', expected, version='2')


def prepare_kernel(profile):
    name = 'kernel' if profile == 'server' else 'kernel-media'
    lock = json.loads((ROOT/'inputs.kernel.lock.json').read_text())
    inputs = {'kernel':lock['kernel'], 'profile':profile}
    inputs['boot_mode'] = 'spi'
    expected = identity(inputs, recipe_files(
        'packaging/bpi-m4-kernel.spec', 'config/kernel.config', 'config/kernel.required.config',
        'packaging/kernel-update-release', 'patches/linux', 'src/linux'))
    linux_key = linux_key_input()
    item = lock['kernel']
    archive = fetch(item['url'], ROOT/'cache/sources'/item['filename'], item['sha256'])
    signature = fetch(item['signature_url'], ROOT/'cache/sources'/item['signature_filename'], item['signature_sha256'])
    verify_linux(archive, signature, linux_key)
    work = fresh_workspace(name)
    # Keep upstream bytes intact in the SRPM; all preparation runs in %prep.
    shutil.copy2(archive, work/'SOURCES'/archive.name)
    fragment = ROOT/('src/linux/media/media.config' if profile == 'media' else 'src/linux/peripherals/fc.config')
    local = re.search(r'^CONFIG_LOCALVERSION="(.*)"$', fragment.read_text(), re.M)[1]
    revision = (ROOT/'packaging/kernel-update-release').read_text().strip()
    if not re.fullmatch(r'[1-9][0-9]*', revision):
        raise ValueError('kernel-update-release must be a positive integer')
    release = item['version']+'-'+local.lstrip('-').replace('-', '_')
    release += '.r'+revision+'.'+fingerprint(expected)[:12]
    (work/'SOURCES/kernel-update-release').write_text(revision+'\n')
    tools = work/'prepared/bpi-m4-kernel-inputs'
    shutil.copytree(ROOT/'src/linux', tools/'src/linux')
    patches=[*sorted((ROOT/'patches/linux').glob('*.patch')),
             *sorted((ROOT/'src/linux/peripherals/reference').glob('*.patch')),
             ROOT/'src/linux/peripherals/mmc-readonly-core.patch',
             ROOT/'src/linux/peripherals/gpio-shared-iso.patch']
    if profile == 'media': patches.extend(sorted((ROOT/'src/linux/media').glob('*.patch')))
    for patch in patches:
        shutil.copy2(patch, work/'SOURCES'/patch.name)
    copy_file(ROOT/'config/kernel.config', tools, 'config/kernel.config')
    shutil.copy2(ROOT/'config/kernel.required.config', work/'SOURCES/kernel.required.config')
    write_json(tools/'provenance.json', expected)
    tar_tree(tools, work/'SOURCES/bpi-m4-kernel-inputs.tar.gz')
    return srpm_build(name, work, 'bpi-m4-kernel.spec', expected,
        {'release':release, 'profile':profile, 'artifact_dir':'usr/lib/bpi-m4/kernels/'+release}, version=item['version'])


def prepare_codecs():
    from .media_codecs import LOCK, validate_lock, verify_source
    name = 'codecs'
    lock = json.loads(LOCK.read_text())
    validate_lock(lock)
    expected = identity(lock, recipe_files('packaging/bpi-m4-native-codecs.spec',
        'bpi_packaging/media_codecs.py', 'scripts/bpi-m4-play', 'docs/MEDIA-CODECS.md'))
    fedora_key = fedora_key_input()
    source = fetch(lock['source']['url'], ROOT/'cache/sources'/lock['source']['filename'], lock['source']['sha256'])
    signature = fetch(lock['signature']['url'], ROOT/'cache/sources'/lock['signature']['filename'], lock['signature']['sha256'])
    key = fetch(lock['key']['url'], ROOT/'cache/keys'/lock['key']['filename'], lock['key']['sha256'])
    work = fresh_workspace(name)
    verify_source(source, signature, key, work/'gpg')
    tree = work/'prepared/bpi-m4-codec-inputs'
    for item in lock['sysroot_packages']:
        package = fetch(item['url'], ROOT/'cache/rpms'/item['filename'], item['sha256'])
        verify_rpm(package, fedora_key)
        copy_file(package, tree, 'sysroot-rpms/'+package.name)
    for relative in ('bpi_packaging/__init__.py', 'bpi_packaging/common.py', 'bpi_packaging/media_codecs.py'):
        copy_file(ROOT/relative, tree, relative)
    for source_, dest in ((ROOT/'scripts/bpi-m4-play','bpi-m4-play'), (ROOT/'docs/MEDIA-CODECS.md','MEDIA-CODECS.md')):
        copy_file(source_, tree, dest)
    metadata = {'inputs':lock, 'license':'LGPL-2.1-or-later', 'hardware_decode':False,
        'system_libraries_replaced':False, 'make_override':'CONFIG_ELBG_FILTER=yes'}
    write_json(tree/'provenance.json', dict(metadata, identity=expected))
    tar_tree(tree, work/'SOURCES/bpi-m4-codec-inputs.tar.gz')
    shutil.copy2(source, work/'SOURCES'/source.name)
    return srpm_build(name, work, 'bpi-m4-native-codecs.spec', expected, metadata)


# Declared Fedora runtime RPMs for the small initramfs; extracted only in the COPR buildroot.
INITRAMFS_PACKAGES = {'bash','coreutils','coreutils-common','glibc','libgcc','ncurses-libs',
    'libmount','libblkid','libsmartcols','libuuid','libeconf','libselinux','pcre2','libcap',
    'util-linux','util-linux-core','libzstd','zlib-ng-compat','xz-libs','libxcrypt','systemd-libs'}

def prepare_sd_boot():
    lock = json.loads((ROOT/'inputs.initramfs.lock.json').read_text())
    runtime = [p for p in lock['packages'] if
               re.match(r'(.+?)-[0-9]', p['filename'])[1] in INITRAMFS_PACKAGES]
    expected = identity({'runtime_rpms':runtime, 'boot_mode':'spi'}, recipe_files(
        'packaging/bpi-m4-sd-boot.spec', 'scripts/bpi-m4-bootctl', 'scripts/bpi-m4-mode',
        'src/initramfs/init-sd', 'src/initramfs/sd-root.bash', 'bpi_packaging/sd_boot.py', 'bpi_packaging/initramfs.py',
        'bpi_packaging/rpm_extract.py', 'docs/KERNEL-UPDATES.md', 'docs/MODES.md', 'licenses/GPL-2.0.txt'))
    fedora_key = fedora_key_input()
    work = fresh_workspace('sd-boot')
    tree = work/'prepared/bpi-m4-sd-boot-inputs'
    for package in runtime:
        path = fetch(package['url'], ROOT/'cache/rpms'/package['filename'], package['sha256'])
        verify_rpm(path, fedora_key)
        copy_file(path, tree, 'runtime-rpms/'+package['filename'])
    for relative in ('bpi_packaging/__init__.py', 'bpi_packaging/common.py',
                     'bpi_packaging/rpm_extract.py', 'bpi_packaging/initramfs.py', 'bpi_packaging/sd_boot.py',
                     'src/initramfs/init-sd', 'src/initramfs/sd-root.bash', 'scripts/bpi-m4-bootctl', 'scripts/bpi-m4-mode',
                     'docs/KERNEL-UPDATES.md', 'docs/MODES.md', 'licenses/GPL-2.0.txt'):
        copy_file(ROOT/relative, tree, relative)
    write_json(tree/'provenance.json', expected)
    tar_tree(tree, work/'SOURCES/bpi-m4-sd-boot-inputs.tar.gz')
    return srpm_build('sd-boot', work, 'bpi-m4-sd-boot.spec', expected,
        {'artifact_dir':'usr/lib/bpi-m4/sd-boot', 'boot_mode':'spi'}, version='2')


def prepare_checks():
    paths = ('Makefile', 'bpi_packaging', 'src/linux', 'src/initramfs', 'patches/linux',
             'packaging', 'scripts', 'tests', 'docs', 'licenses', 'config',
             'inputs.kernel.lock.json', 'inputs.initramfs.lock.json', 'inputs.media-codecs.lock.json')
    files = recipe_files(*paths)
    expected = identity({}, files)
    work = fresh_workspace('checks')
    tree = work/'prepared/bpi-m4-build-checks'
    for source in sorted(set(files)):
        if source.is_file(): copy_file(source, tree, source.relative_to(ROOT))
    tar_tree(tree, work/'SOURCES/bpi-m4-build-checks.tar.gz')
    return srpm_build('checks', work, 'bpi-m4-build-checks.spec', expected)


def main():
    p = argparse.ArgumentParser(description='Prepare a source RPM inside the COPR Git source worker')
    p.add_argument('component', choices=['board', 'kernel', 'sd-boot', 'codecs', 'checks'])
    p.add_argument('--profile', choices=['server', 'media'], default='server')
    args = p.parse_args()
    {'board':prepare_board, 'kernel':lambda:prepare_kernel(args.profile),
     'sd-boot':prepare_sd_boot, 'codecs':prepare_codecs,
     'checks':prepare_checks}[args.component]()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError) as error:
        raise SystemExit('Build failed: '+str(error))
