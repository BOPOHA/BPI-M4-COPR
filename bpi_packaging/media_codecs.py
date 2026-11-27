import platform
"""Pinned upstream native decoders in a private COPR-built RPM.

Only libavcodec is overridden for bpi-m4-play. Fedora's libavutil and other
libraries remain in use; their ABI is checked before packaging.
"""
import re
import shutil
import subprocess
from pathlib import Path
from .common import ROOT, FEDORA_FPR, run, verify_key

FFMPEG_FPR = 'FCF986EA15E6E293A5644F10B4322F04D67658D8'
LOCK = ROOT/'inputs.media-codecs.lock.json'


def validate_lock(lock):
    if (lock['schema'], lock['version'], lock['abi']) != (1, '9.0.2', 63):
        raise ValueError('Native codec source/ABI needs an explicit recipe update')
    if lock['key']['fingerprint'] != FFMPEG_FPR:
        raise ValueError('Native codec lock cannot replace the upstream trust anchor')
    for name in ('source', 'signature', 'key'):
        item = lock[name]
        if Path(item['filename']).name != item['filename']:
            raise ValueError('Invalid codec input filename')
    for item in lock['sysroot_packages']:
        if item['arch'] != 'aarch64' or item['signer'] != FEDORA_FPR:
            raise ValueError('Codec sysroot requires Fedora-signed aarch64 inputs')
        if Path(item['filename']).name != item['filename']:
            raise ValueError('Invalid sysroot input filename')


def verify_source(archive, signature, key, home):
    verify_key(key, FFMPEG_FPR)
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    base = ['gpg', '--batch', '--no-options', '--homedir', home, '--no-autostart']
    run(base+['--import', key], capture=True)
    status = run(base+['--status-fd=1', '--verify', signature, archive], capture=True).stdout
    if not any(line.startswith('[GNUPG:] VALIDSIG '+FFMPEG_FPR+' ') for line in status.splitlines()):
        raise ValueError('Native codec source does not have the pinned upstream signature')
    return status


def prepare_sysroot(inputs):
    """Extract verified target development RPMs inside the COPR %prep stage."""
    sysroot = inputs/'sysroot'
    sysroot.mkdir()
    packages = sorted((inputs/'sysroot-rpms').glob('*.rpm'))
    if not packages:
        raise ValueError('Missing codec sysroot RPMs')
    for package in packages:
        producer = subprocess.Popen(['rpm2cpio', str(package)], stdout=subprocess.PIPE)
        try:
            subprocess.run(['cpio', '--quiet', '-idm', '--no-absolute-filenames', '--no-preserve-owner'],
                cwd=sysroot, stdin=producer.stdout, check=True)
        finally:
            producer.stdout.close()
            if producer.wait() != 0:
                raise ValueError('Verified codec sysroot extraction failed')
    for name in ('lib', 'lib64'):
        path = sysroot/name
        if path.is_dir() and not path.is_symlink():
            target = sysroot/'usr'/name
            target.mkdir(parents=True, exist_ok=True)
            for child in path.iterdir():
                shutil.move(child, target/child.name)
            path.rmdir()
        if not path.is_symlink():
            path.symlink_to('usr/'+name)
    (sysroot/'usr/lib64/libgcc_s.so').symlink_to('libgcc_s.so.1')
    return sysroot


def dynamic_symbols(path):
    rows = run([('readelf' if platform.machine() == 'aarch64' else 'aarch64-linux-gnu-readelf'), '--dyn-syms', '--wide', path], capture=True).stdout
    defined, needed = set(), set()
    for row in rows.splitlines():
        fields = row.split()
        if len(fields) >= 8 and re.fullmatch(r'\d+:', fields[0]):
            name = fields[7].replace('@@', '@')
            (needed if fields[6] == 'UND' else defined).add(name)
    return defined, needed


def audit_abi(library, root):
    header = run([('readelf' if platform.machine() == 'aarch64' else 'aarch64-linux-gnu-readelf'), '-h', library], capture=True).stdout
    dynamic = run([('readelf' if platform.machine() == 'aarch64' else 'aarch64-linux-gnu-readelf'), '-d', library], capture=True).stdout
    if 'AArch64' not in header or '(SONAME)' not in dynamic or '[libavcodec.so.63]' not in dynamic:
        raise ValueError('Native codec architecture/SONAME mismatch')
    dependencies = set(re.findall(r'\(NEEDED\).*\[([^]]+)\]', dynamic))
    if dependencies != {'libavutil.so.61', 'libm.so.6', 'libc.so.6'}:
        raise ValueError('Unexpected native codec dependencies: '+str(dependencies))
    if root is None:
        return {'architecture':'AArch64', 'soname':'libavcodec.so.63',
                'needed':sorted(dependencies), 'missing_versioned_symbols':None}
    exported, required = dynamic_symbols(library)
    utility, _ = dynamic_symbols(root/'usr/lib64/libavutil.so.61')
    missing = {s for s in required if '@LIBAVUTIL_' in s} - utility
    # Fedora's avfilter also calls avpriv_elbg_do/free even with encoders off.
    for path in [root/'usr/bin/mpv', *(root/'usr/lib64').glob('libav*.so.*'),
                 *(root/'usr/lib64').glob('libsw*.so.*')]:
        if path.is_file() and not path.name.startswith('libavcodec.'):
            _, consumer = dynamic_symbols(path)
            missing |= {s for s in consumer if '@LIBAVCODEC_' in s} - exported
    if missing:
        raise ValueError('Native codec is incompatible with Fedora consumers: '+', '.join(sorted(missing)))
    return {'architecture':'AArch64', 'soname':'libavcodec.so.63',
            'needed':sorted(dependencies), 'missing_versioned_symbols':[]}
