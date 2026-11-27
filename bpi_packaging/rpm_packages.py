"""Prepare self-contained SRPMs and track local RPM product integrity.

Make owns dependencies. Mock runs rpmbuild in a clean Fedora buildroot.
This module never installs packages on the host or writes a block device.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile

from .common import ROOT, fetch, run, sha, verify_rpm, write_json
from .inputs import fedora_key_input, linux_key_input, verify_linux

OUT = ROOT/'out/rpms'
SPECS = ROOT/'packaging'
WORK = ROOT/'work/rpms'
MOCK_CONFIG = SPECS/'mock/bpi-m4-f45-cross.cfg'
RPKG_CONFIG = SPECS/'rpkg.conf'


def build_environment():
    if os.environ.get('BPI_COPR_SOURCE') == '1':
        # Stable across source worker architectures and installed Mock versions.
        # Inputs and all source-preparation recipes are fingerprinted separately.
        return {'mode': 'copr-scm', 'format': 1}
    configs = [RPKG_CONFIG, MOCK_CONFIG, Path('/etc/mock/fedora-45-x86_64.cfg'),
        Path('/etc/mock/templates/fedora-branched.tpl'), Path('/etc/mock/site-defaults.cfg'),
        Path('/etc/mock/chroot-aliases.cfg'), Path.home()/'.config/mock.cfg']
    return {'mock':run(['rpm', '-q', 'mock', 'mock-core-configs', 'rpkg', 'rpm-build'], capture=True).stdout.splitlines(),
        'configs':{str(path):sha(path) for path in configs if path.is_file()}}


def identity(inputs, files):
    value = {'inputs':inputs, 'recipes':{str(p.relative_to(ROOT)):sha(p) for p in sorted(set(files))}}
    value['rpm_build'] = build_environment()
    return value


def recipe_files(*paths):
    files = [Path(__file__), ROOT/'bpi_packaging/common.py', ROOT/'bpi_packaging/inputs.py', ROOT/'scripts/clean-rpm-work.bash', ROOT/'scripts/build-rpm.bash', ROOT/'scripts/build-srpm.bash', RPKG_CONFIG]
    if os.environ.get('BPI_COPR_SOURCE') == '1':
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


def read_cpio(path, destination):
    """Extract RPM/SRPM regular files without invoking a shell or trusting paths."""
    destination.mkdir(parents=True, exist_ok=True)
    payload = subprocess.run(['rpm2cpio', str(path)], stdout=subprocess.PIPE, check=True).stdout
    offset = 0
    while offset + 110 <= len(payload):
        header = payload[offset:offset+110]
        if header[:6] not in (b'070701', b'070702'):
            raise ValueError('Unsupported RPM cpio encoding')
        fields = [int(header[6+i*8:14+i*8], 16) for i in range(13)]
        mode, size, length = fields[1], fields[6], fields[11]
        name = payload[offset+110:offset+110+length-1].decode()
        offset = (offset+110+length+3)&~3
        content = payload[offset:offset+size]
        offset = (offset+size+3)&~3
        if len(content) != size:
            raise ValueError('Truncated RPM payload')
        if name == 'TRAILER!!!': return
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe RPM payload path')
        target = destination/relative
        if stat.S_ISDIR(mode): target.mkdir(parents=True, exist_ok=True)
        elif stat.S_ISREG(mode):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(mode&0o777)
        else:
            raise ValueError('Unexpected non-regular local RPM payload')
    raise ValueError('RPM payload lacks cpio trailer')


def receipt(name, *, source=False):
    path = (ROOT/'out/srpms' if source else OUT)/(name+'.json')
    if not path.is_file(): raise ValueError('Missing '+name+' RPM; run make rpms PROFILE=server or media')
    record = json.loads(path.read_text())
    for kind in ('rpms', 'srpms'):
        for item in record[kind]:
            product = ROOT/item['path']
            if not product.is_file() or sha(product) != item['sha256']:
                raise ValueError('Local RPM product missing or changed: '+str(product))
    return record


def cached(name, expected, *, source=False):
    try: record = receipt(name, source=source)
    except (ValueError, FileNotFoundError): return None
    if record['identity'] != expected: return None
    for item in record['rpms']+record['srpms']:
        if item.get('alias'):
            alias = ROOT/item['alias']
            product = ROOT/item['path']
            if not alias.is_symlink() or alias.resolve() != product.resolve():
                link = alias.with_suffix(alias.suffix+'.partial')
                link.unlink(missing_ok=True)
                link.symlink_to(os.path.relpath(product, alias.parent))
                link.replace(alias)
    # An input may have been touched without changing its content. A successful
    # Make recipe must advance its products past those input timestamps.
    for item in record['rpms']+record['srpms']:
        if item.get('alias'): os.utime(ROOT/item['path'], None)
    os.utime((ROOT/'out/srpms' if source else OUT)/(name+'.json'), None)
    print('Reusing '+name+(' SRPM' if source else ' RPM')+' products', flush=True)
    return record


def fresh_workspace(name):
    work = WORK/name
    run([ROOT/'scripts/clean-rpm-work.bash', work])
    for directory in ('SOURCES', 'SPECS', 'srpm-result', 'result'):
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


def srpm_build(name, work, spec_name, expected, aliases, metadata=None, version=''):
    print('rpkg srpm '+name+'; log '+str(work/'srpm.log'), flush=True)
    run([ROOT/'scripts/build-srpm.bash', RPKG_CONFIG, SPECS/spec_name, work,
         fingerprint(expected)[:12], expected['inputs'].get('profile', 'server'), version])
    sources = sorted((work/'srpm-result').glob('*.src.rpm'))
    if len(sources) != 1: raise ValueError('rpkg must produce exactly one SRPM')
    if name == 'firmware':
        firmware = work/'srpm-result/bluecore.audio'
        run(['sha256sum', '--check', '--strict'],
            input=(metadata['sha256']+'  '+str(firmware)+'\n').encode())
        size = int(run(['stat', '-Lc', '%s', firmware], capture=True).stdout)
        if size != metadata['bytes'] or not 0 < size <= 0x500000:
            raise ValueError('Media firmware size exceeds its pinned load area')
        cache = ROOT/'cache/firmware/bluecore.audio'
        cache.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(firmware, cache)
    record = {'schema':1, 'identity':expected, 'rpms':[], 'srpms':[
        publish_product(sources[0], ROOT/'out/srpms', name+'.src.rpm')],
        'metadata':metadata or {}, 'aliases':aliases}
    write_json(ROOT/'out/srpms'/(name+'.json'), record)
    return record


def audit_products(name, work, products, metadata):
    if name != 'codecs' and not name.startswith('boot-'): return
    if len(products) != 1: raise ValueError('Ambiguous '+name+' RPM products')
    read_cpio(products[0], work/'audit')
    if name == 'codecs':
        library = work/'audit/usr/lib64/bpi-m4-codecs/libavcodec.so.63'
        audit = json.loads((work/'audit/usr/share/doc/bpi-m4-native-codecs/abi-audit.json').read_text())
        if audit['library_sha256'] != sha(library):
            raise ValueError('Mock ABI audit does not match packaged codec library')
        metadata.update(audit)
        provides = run(['rpm', '-qp', '--provides', products[0]], capture=True).stdout
        if 'libavcodec.so.' in provides: raise ValueError('Private codec RPM provides system FFmpeg capabilities')
    else:
        profile = name.removeprefix('boot-')
        directory = work/'audit/usr/lib/bpi-m4'/('boot-'+profile)
        metadata.update(json.loads((directory/'boot-manifest.json').read_text()))
        metadata['artifacts_sha256']['u-boot-bpi-m4.bin'] = sha(directory/'u-boot-bpi-m4.bin')


def rebuild(name, jobs):
    source = receipt(name, source=True)
    expected = source['identity']
    # Reject a source record prepared for another toolchain/configuration.
    if expected['rpm_build'] != build_environment():
        raise ValueError('Build environment changed; regenerate the SRPM with make srpm-*')
    # Compare the selected SRPM before repairing aliases in a binary cache.
    # A regenerated SRPM can have the same recipe identity but different bytes.
    try:
        previous = receipt(name) if name != 'checks' else None
    except (ValueError, FileNotFoundError):
        previous = None
    if previous and previous['srpms'] == source['srpms']:
        reused = cached(name, expected)
        if reused: return reused
    work = WORK/name
    for directory in ('result', 'audit'):
        run([ROOT/'scripts/clean-rpm-work.bash', work/directory])
    (work/'result').mkdir(parents=True)
    srpm = ROOT/source['srpms'][0]['path']
    print('mock '+name+'; log '+str(work/'mock.log'), flush=True)
    unique = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]+'-'+name
    run([ROOT/'scripts/build-rpm.bash', MOCK_CONFIG, srpm, work, unique, str(jobs)])
    binaries = sorted(p for p in (work/'result').glob('*.rpm') if not p.name.endswith('.src.rpm'))
    if not binaries: raise ValueError('Mock produced no binary RPMs')
    metadata = dict(source['metadata'])
    audit_products(name, work, binaries, metadata)
    record = {'schema':1, 'identity':expected, 'rpms':[], 'srpms':source['srpms'],
        'metadata':metadata, 'buildroot_packages':(work/'result/installed_pkgs.log').read_text()}
    for product in binaries:
        package_name = run(['rpm', '-qp', '--qf', '%{NAME}', product], capture=True).stdout
        record['rpms'].append(publish_product(product, OUT, source['aliases'][package_name]+'.rpm'))
    write_json(OUT/(name+'.json'), record)
    return record


def prepare_board():
    name = 'board'
    files = recipe_files('packaging/bpi-m4-board-support.spec', 'packaging/files',
        'scripts/bpi-m4-hdmi-start', 'docs/FIRST-BOOT.md',
        'docs/MEDIA-FIRMWARE.md', 'licenses/GPL-2.0.txt')
    expected = identity({}, files)
    previous = cached(name, expected, source=True)
    if previous: return previous
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
    return srpm_build(name, work, 'bpi-m4-board-support.spec', expected,
        {package:package for package in
         ('bpi-m4-board-support', 'bpi-m4-media-support', 'bpi-m4-media')}, version='2')


def prepare_kernel(profile, updates=False):
    name = 'kernel-'+profile
    package = 'bpi-m4-kernel-'+profile
    if updates:
        name = 'kernel-updates' if profile == 'server' else 'kernel-media-updates'
        if profile == 'server': package = 'bpi-m4-kernel'
    lock = json.loads((ROOT/'inputs.kernel.lock.json').read_text())
    inputs = {'kernel':lock['kernel'], 'profile':profile}
    if updates: inputs['boot_mode'] = 'spi'
    expected = identity(inputs, recipe_files(
        'packaging/bpi-m4-kernel.spec', 'config/kernel.config', 'config/kernel.required.config',
        'packaging/kernel-update-release', 'patches/linux', 'src/linux'))
    previous = cached(name, expected, source=True)
    if previous: return previous
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
    release = item['version']+local
    revision = (ROOT/'packaging/kernel-update-release').read_text().strip()
    if not re.fullmatch(r'[1-9][0-9]*', revision):
        raise ValueError('kernel-update-release must be a positive integer')
    if updates:
        release = item['version']+'-'+local.lstrip('-').replace('-', '_')
        release += '.r'+revision+'.'+fingerprint(expected)[:12]
    (work/'SOURCES/bpi-boot-mode').write_text('spi\n' if updates else 'sd\n')
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
        {package:'bpi-m4-'+name, package+'-devel':package+'-devel'},
        {'release':release, 'profile':profile, 'artifact_dir':'usr/lib/bpi-m4/kernels/'+release if updates
         else 'usr/lib/bpi-m4/kernel-'+profile}, version=item['version'])


def prepare_firmware():
    name = 'firmware'
    record = json.loads((ROOT/'config/media-firmware.json').read_text())
    expected = identity(record, recipe_files('packaging/bpi-m4-media-firmware.spec',
        'config/media-firmware.json', 'docs/MEDIA-FIRMWARE.md'))
    previous = cached(name, expected, source=True)
    if previous: return previous
    work = fresh_workspace(name)
    write_json(work/'SOURCES/provenance.json', record)
    shutil.copy2(ROOT/'docs/MEDIA-FIRMWARE.md', work/'SOURCES/MEDIA-FIRMWARE.md')
    # Reuse verified bytes offline; otherwise let RPM fetch its remote Source0.
    cache = ROOT/'cache/firmware/bluecore.audio'
    if cache.is_file():
        verified = subprocess.run(['sha256sum', '--check', '--status'],
            input=record['sha256']+'  '+str(cache)+'\n', text=True).returncode == 0
        if verified: shutil.copy2(cache, work/'SOURCES/bluecore.audio')
    # RPM fetches the declared Source0. Its %prep enforces hash, size and origin.
    return srpm_build(name, work, 'bpi-m4-media-firmware.spec', expected,
        {'bpi-m4-media-firmware':'bpi-m4-media-firmware'}, record)


def prepare_codecs():
    from .media_codecs import LOCK, validate_lock, verify_source
    name = 'codecs'
    lock = json.loads(LOCK.read_text())
    validate_lock(lock)
    expected = identity(lock, recipe_files('packaging/bpi-m4-native-codecs.spec',
        'bpi_packaging/media_codecs.py', 'scripts/bpi-m4-play', 'docs/MEDIA-CODECS.md'))
    previous = cached(name, expected, source=True)
    if previous: return previous
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
    return srpm_build(name, work, 'bpi-m4-native-codecs.spec', expected,
        {'bpi-m4-native-codecs':'bpi-m4-native-codecs'}, metadata)



# Declared Fedora runtime RPMs for the small initramfs; extracted only in Mock.
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
    previous = cached('sd-boot', expected, source=True)
    if previous: return previous
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
        {'bpi-m4-sd-boot':'bpi-m4-sd-boot'},
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
    return srpm_build('checks', work, 'bpi-m4-build-checks.spec', expected,
                      {'bpi-m4-build-checks':'bpi-m4-build-checks'})


def main():
    p = argparse.ArgumentParser(description='Prepare sources and build local RPMs through checked-in spec files')
    p.add_argument('component', nargs='?', choices=['board', 'kernel', 'kernel-updates', 'sd-boot', 'codecs', 'firmware', 'checks'])
    action = p.add_mutually_exclusive_group()
    action.add_argument('--srpm', action='store_true', help='Prepare only the source RPM')
    action.add_argument('--rebuild', action='store_true', help='Rebuild the existing source RPM')
    p.add_argument('--write-toolchain', type=Path)
    p.add_argument('--profile', choices=['server', 'media'], default='server')
    p.add_argument('--jobs', type=int, default=8)
    args = p.parse_args()
    if not 1 <= args.jobs <= 64: p.error('jobs must be 1..64')
    if args.write_toolchain:
        value = build_environment()
        if not args.write_toolchain.exists() or json.loads(args.write_toolchain.read_text()) != value:
            write_json(args.write_toolchain, value)
        return
    if not args.component: p.error('specify a component or --write-toolchain')
    name = args.component + ('-'+args.profile if args.component in ('kernel',) else '')
    if args.component == 'kernel-updates' and args.profile == 'media':
        name = 'kernel-media-updates'
    if not args.rebuild:
        {'board':prepare_board, 'kernel':lambda:prepare_kernel(args.profile),
         'kernel-updates':lambda:prepare_kernel(args.profile, updates=True),
         'sd-boot':prepare_sd_boot,
         'codecs':prepare_codecs, 'firmware':prepare_firmware, 'checks':prepare_checks}[args.component]()
    if not args.srpm: rebuild(name, args.jobs)



if __name__ == '__main__':
    try:
        main()
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError) as error:
        raise SystemExit('Build failed: '+str(error))
