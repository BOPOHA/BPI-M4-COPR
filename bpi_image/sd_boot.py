"""Build the generic target-Fedora initramfs inside Mock."""
from pathlib import Path
import sys
from .rpm_extract import extract
from .common import run
from .initramfs import build


def prepare(inputs):
    inputs = Path(inputs).resolve()
    runtime = inputs/'runtime'
    runtime.mkdir()
    for name, target in [('bin', 'usr/bin'), ('sbin', 'usr/sbin'),
                         ('lib', 'usr/lib'), ('lib64', 'usr/lib64')]:
        if name == 'sbin':
            (runtime/'usr/sbin').symlink_to('bin')
        else:
            (runtime/target).mkdir(parents=True, exist_ok=True)
        (runtime/name).symlink_to(target)
    for package in sorted((inputs/'runtime-rpms').glob('*.rpm')):
        extract(package, runtime)
    artifacts = inputs/'artifacts'
    artifacts.mkdir()
    build(runtime, artifacts/'initramfs.img')
    checksums = run(['sha256sum', 'initramfs.img', 'initramfs-manifest.json'],
                    cwd=artifacts, capture=True).stdout
    (artifacts/'SHA256SUMS').write_text(checksums)


if __name__ == '__main__':
    prepare(sys.argv[1])
