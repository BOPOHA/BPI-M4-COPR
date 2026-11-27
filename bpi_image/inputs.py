"""Explicit lock refresh and signature-verified consumption of fixed inputs."""
import datetime
import json
import lzma
from pathlib import Path
import shutil
import subprocess
import tempfile
import yaml
from .common import ROOT, FEDORA_FPR, LINUX_FPR, approved_url, dnf, fetch, run, sha, verify_key, verify_rpm, write_json

def fedora_key_input():
    fedora = ROOT / 'cache/keys/fedora-45.asc'
    fedora.parent.mkdir(parents=True, exist_ok=True)
    if not fedora.exists():
        shutil.copyfile('/usr/share/pki/rpm-gpg/RPM-GPG-KEY-fedora-45-primary', fedora)
    verify_key(fedora, FEDORA_FPR)
    return fedora

def linux_key_input():
    linux = ROOT / 'cache/keys/gregkh.asc'
    if not linux.exists():
        fetch('https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x' + LINUX_FPR, linux)
    verify_key(linux, LINUX_FPR)
    return linux

def verify_linux(archive, signature, key):
    verify_key(key, LINUX_FPR)
    home = ROOT / 'cache/gpg'
    home.mkdir(mode=0o700, exist_ok=True)
    # No private keys, agent or web-of-trust decisions are needed.
    run(['gpg', '--batch', '--no-options', '--homedir', home, '--no-autostart', '--import', key], capture=True)
    # Independent server/media Make jobs must not share a verification file.
    with tempfile.NamedTemporaryFile(prefix='linux-verify-', suffix='.tar', dir=ROOT/'cache/sources', delete=False) as out:
        plain = Path(out.name)
        with lzma.open(archive) as source: shutil.copyfileobj(source, out)
    try:
        result = run(['gpg', '--batch', '--no-options', '--homedir', home, '--status-fd=1',
                      '--verify', signature, plain], capture=True).stdout
        if not any(line.startswith('[GNUPG:] VALIDSIG ' + LINUX_FPR + ' ') for line in result.splitlines()):
            raise ValueError('Linux source signer does not match pinned fingerprint')
        return result
    finally:
        plain.unlink(missing_ok=True)

