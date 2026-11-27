"""Small build primitives; subprocess arguments never pass through a shell."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.parse

ROOT = Path(__file__).resolve().parent.parent
FEDORA_FPR = '4F50A6114CD5C6976A7F1179655A4B02F577861E'
LINUX_FPR = '647F28654894E3BD457199BE38DBBDC86092693E'

def run(args, *, cwd=None, capture=False, log=None, **kw):
    args = [str(x) for x in args]
    env = dict(os.environ, CCACHE_DISABLE='1', LC_ALL='C', SYSTEMD_OFFLINE='1')
    if log:
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        with Path(log).open('w') as out:
            return subprocess.run(args, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT, check=True, **kw)
    return subprocess.run(args, cwd=cwd, env=env, check=True, text=capture,
                          stdout=subprocess.PIPE if capture else None, **kw)

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

def approved_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or p.username or p.password:
        raise ValueError('Inputs require HTTPS without embedded credentials')
    allowed = {'dl.fedoraproject.org', 'kojipkgs.fedoraproject.org', 'cdn.kernel.org', 'www.kernel.org', 'keyserver.ubuntu.com', 'codecs.fedoraproject.org', 'ffmpeg.org'}
    if p.hostname not in allowed:
        raise ValueError(f'Unapproved input host: {p.hostname}')
    # Fedora's official OpenH264 endpoint redirects to HTTP. Use Cisco's
    # HTTPS endpoint for that exact RPM path; retain hash/signature checks.
    if p.hostname == 'codecs.fedoraproject.org' and not p.query and not p.fragment:
        codec = re.fullmatch(r'/openh264/45/aarch64/Packages/o/(openh264-[\w.+-]+\.aarch64\.rpm)', p.path)
        if codec:
            return 'https://ciscobinary.openh264.org/'+codec[1]
    return url

def fetch(url, destination, expected=None):
    url = approved_url(url)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or (expected and sha(path) != expected):
        temporary = path.with_name(path.name + '.part')
        run(['curl', '--fail', '--location', '--proto', '=https', '--proto-redir', '=https',
             '--connect-timeout', '20', '--max-time', '600', '--retry', '3', '-o', temporary, url])
        if expected and sha(temporary) != expected:
            temporary.unlink()
            raise ValueError(f'Input SHA-256 mismatch: {path.name}')
        temporary.replace(path)
    if expected and sha(path) != expected:
        raise ValueError(f'Input SHA-256 mismatch: {path.name}')
    return path

def rpm_db():
    db = ROOT / 'cache/rpmdb'
    db.mkdir(parents=True, exist_ok=True)
    return db

def verify_key(path, fingerprint):
    result = run(['gpg', '--batch', '--no-options', '--show-keys', '--with-colons', path], capture=True).stdout
    fingerprints = [line.split(':')[9] for line in result.splitlines() if line.startswith('fpr:')]
    if not fingerprints or fingerprints[0] != fingerprint:
        raise ValueError('Unexpected primary signing key fingerprint')

def verify_rpm(path, key):
    verify_key(key, FEDORA_FPR)
    run(['rpm', '--dbpath', rpm_db(), '--import', key], capture=True)
    output = run(['rpmkeys', '--dbpath', rpm_db(), '--checksig', path], capture=True).stdout
    if 'signatures OK' not in output or 'NOT OK' in output or 'NOKEY' in output:
        raise ValueError(f'Unsigned/untrusted RPM: {path}')
    return path.name + ': digests signatures OK'

def dnf_config(release=45):
    directory = ROOT / 'cache/dnf'
    (directory / 'repos').mkdir(parents=True, exist_ok=True)
    key = ROOT / 'cache/keys/fedora-45.asc'
    base = 'https://dl.fedoraproject.org/pub/fedora/linux'
    repos = [('fedora', f'{base}/releases/{release}/Everything/aarch64/os/', 1),
             ('updates', f'{base}/updates/{release}/Everything/aarch64/', 1),
             ('fedora-source', f'{base}/releases/{release}/Everything/source/tree/', 0),
             ('updates-source', f'{base}/updates/{release}/Everything/source/tree/', 0),
             ('fedora-cisco-openh264', f'https://codecs.fedoraproject.org/openh264/{release}/aarch64/', 0)]
    text = ''
    for name, url, enabled in repos:
        text += f'[{name}]\nname={name} official Fedora\nbaseurl={url}\nenabled={enabled}\ngpgcheck=1\ngpgkey=file://{key}\nskip_if_unavailable=0\n\n'
    (directory / 'repos/fedora.repo').write_text(text)
    conf = directory / 'dnf.conf'
    conf.write_text(f'[main]\nreposdir={directory}/repos\ncachedir={directory}/cache\nlogdir={directory}/log\npersistdir={directory}/persist\ninstall_weak_deps=False\ngpgcheck=True\n')
    return conf

def dnf(release=45):
    return ['dnf', '--config=' + str(dnf_config(release)), '--releasever=' + str(release), '--forcearch=aarch64']
