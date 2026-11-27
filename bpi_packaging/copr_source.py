"""COPR make_srpm bridge: prepare one pinned, self-contained source package."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from .common import ROOT, run

# The Media SPEC symlink is a selector; both profiles use the shared kernel recipe.
PACKAGES = {
    'bpi-m4-board-support.spec': ('board', 'server', 'board'),
    'bpi-m4-kernel.spec': ('kernel-updates', 'server', 'kernel-updates'),
    'bpi-m4-kernel-media.spec': ('kernel-updates', 'media', 'kernel-media-updates'),
    'bpi-m4-sd-boot.spec': ('sd-boot', 'server', 'sd-boot'),
    'bpi-m4-native-codecs.spec': ('codecs', 'server', 'codecs'),
    'bpi-m4-build-checks.spec': ('checks', 'server', 'checks'),
    'bpi-m4-module-checks.spec': ('module-checks', 'server', 'module-checks'),
}


def selection(spec):
    path = Path(spec)
    if not path.is_absolute():
        path = ROOT / path
    # Preserve the selector's basename while checking its parent and target.
    if path.parent.resolve() != ROOT / 'packaging' or not path.is_file():
        raise ValueError('SPEC must be a checked-in packaging/ entry')
    if path.resolve().parent != ROOT / 'packaging' or path.name not in PACKAGES:
        raise ValueError('Unsupported COPR source package; firmware publication is excluded')
    return PACKAGES[path.name]


def prepare(spec, outdir):
    component, profile, alias = selection(spec)
    destination = Path(outdir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    # Source preparation needs no Mock, host compiler, or host package install.
    os.environ['BPI_COPR_SOURCE'] = '1'
    # A root source worker may receive a checkout owned by its clone service.
    # Scope Git's ownership exception to subprocesses, never host Git config.
    count = int(os.environ.get('GIT_CONFIG_COUNT', '0'))
    os.environ['GIT_CONFIG_COUNT'] = str(count + 1)
    os.environ['GIT_CONFIG_KEY_' + str(count)] = 'safe.directory'
    os.environ['GIT_CONFIG_VALUE_' + str(count)] = str(ROOT)
    os.environ['PATH'] = str(ROOT / 'scripts/rpm-tools') + ':' + os.environ['PATH']
    if component == 'module-checks':
        run([ROOT / 'scripts/prepare-module-check.bash'])
        source = (ROOT / 'out/srpms/module-checks.src.rpm').resolve()
    else:
        run([sys.executable, '-m', 'bpi_packaging.rpm_packages', component,
             '--profile', profile, '--srpm'])
        record = json.loads((ROOT / 'out/srpms' / (alias + '.json')).read_text())
        if len(record['srpms']) != 1:
            raise ValueError('Exactly one prepared SRPM required')
        source = ROOT / record['srpms'][0]['path']
    target = destination / source.name
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    print('COPR source package: ' + str(target), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True)
    parser.add_argument('--outdir', required=True)
    args = parser.parse_args()
    prepare(args.spec, args.outdir)


if __name__ == '__main__':
    main()
