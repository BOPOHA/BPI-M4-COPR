"""Build a small newc initrd from declared target Fedora RPM contents."""
import gzip
import platform
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
from .common import ROOT, run, sha, write_json

def runtime_command(stage, binary):
    if platform.machine() == 'aarch64':
        loader = target_path(stage, '/lib/ld-linux-aarch64.so.1')
        library_path = ':'.join(str(stage/x) for x in ('usr/lib64','usr/lib','lib64','lib'))
        return [loader, '--library-path', library_path, target_path(stage, binary)]
    return ['qemu-aarch64-static', '-L', stage, stage/binary.lstrip('/')]

def target_path(root, name):
    """Resolve absolute target symlinks inside root, never against the host."""
    parts = list(PurePosixPath('/' + name.lstrip('/')).parts[1:])
    resolved = []
    count = 0
    while parts:
        part = parts.pop(0)
        if part in ('', '.'):
            continue
        if part == '..':
            if not resolved: raise ValueError('Target path escapes installroot')
            resolved.pop()
            continue
        path = root.joinpath(*resolved, part)
        if path.is_symlink():
            count += 1
            if count > 40: raise ValueError('Target symlink loop')
            value = os.readlink(path)
            if value.startswith('/'): resolved = []
            parts = list(PurePosixPath(value).parts[1:] if value.startswith('/') else PurePosixPath(value).parts) + parts
        else:
            resolved.append(part)
    return root.joinpath(*resolved)

def require_arm64(path):
    data = Path(path).read_bytes()[:64]
    if data[:4] != b'\x7fELF' or data[4] != 2 or data[5] != 1 or struct.unpack_from('<H', data, 18)[0] != 183:
        raise ValueError(f'Expected target aarch64 ELF: {path}')

def closure(root, paths):
    result = set()
    expanded = set()
    pending = list(paths)
    while pending:
        name = pending.pop()
        source = target_path(root, name)
        relative = '/' + source.relative_to(root).as_posix()
        if relative in expanded: continue
        require_arm64(source)
        expanded.add(relative)
        result.add(relative)
        headers = run([('readelf' if platform.machine() == 'aarch64' else 'aarch64-linux-gnu-readelf'), '-l', '-d', source], capture=True).stdout
        interpreter = re.search(r'Requesting program interpreter: (.*?)\]', headers)
        if interpreter: pending.append(interpreter[1])
        for lib in re.findall(r'\(NEEDED\).*?\[(.*?)\]', headers):
            soname = next((name for directory in ('usr/lib64', 'usr/lib', 'lib64', 'lib')
                           if target_path(root, name := '/' + directory + '/' + lib).is_file()), None)
            found = target_path(root, soname) if soname else None
            if found is None: raise ValueError(f'Missing target dependency {lib}')
            pending.append('/' + found.relative_to(root).as_posix())
            # DT_NEEDED uses the SONAME, so include its symlink as well.
            result.add(soname)
    return result

def copy_target(root, stage, name):
    source = root / name.lstrip('/')
    dest = stage / name.lstrip('/')
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        value = os.readlink(source)
        if not dest.is_symlink(): dest.symlink_to(value)
        actual = target_path(root, name)
        copy_target(root, stage, '/' + actual.relative_to(root).as_posix())
    elif source.is_file():
        shutil.copy2(source, dest)
    else:
        # /bin and /lib are merged-/usr; resolve without host leakage.
        actual = target_path(root, name)
        if not actual.is_file(): raise ValueError(f'Missing initramfs input {name}')
        shutil.copy2(actual, dest)

def newc(stage):
    data = bytearray()
    paths = sorted(stage.rglob('*'))
    for inode, p in enumerate(paths + [None], 1):
        if p is None:
            name, content, mode = 'TRAILER!!!', b'', 0
        else:
            name = p.relative_to(stage).as_posix()
            st = p.lstat()
            mode = st.st_mode
            content = os.readlink(p).encode() if p.is_symlink() else p.read_bytes() if p.is_file() else b''
        encoded = name.encode() + b'\0'
        fields = [inode, mode, 0, 0, 1, 0, len(content), 0, 0, 0, 0, len(encoded), 0]
        data += b'070701' + b''.join(f'{x:08x}'.encode() for x in fields) + encoded
        data += b'\0' * (-len(data) % 4)
        data += content
        data += b'\0' * (-len(data) % 4)
    data += b'\0' * (-len(data) % 512)
    return bytes(data)

def build(root, output, config=None):
    stage = output.parent/'initramfs-root'
    stage.mkdir(exist_ok=False)
    for directory in ('dev', 'proc', 'sys', 'run', 'sysroot', 'etc', 'usr/bin', 'usr/lib64'):
        (stage/directory).mkdir(parents=True, exist_ok=True)
    for name, destination in [('bin', 'usr/bin'), ('sbin', 'usr/sbin'), ('lib', 'usr/lib'), ('lib64', 'usr/lib64')]:
        (stage/name).symlink_to(destination)
    (stage/'usr/sbin').mkdir(exist_ok=True)
    (stage/'usr/lib').mkdir(exist_ok=True)
    binaries = ['/usr/bin/bash', '/usr/bin/mount', '/usr/bin/mkdir', '/usr/bin/sleep', '/usr/bin/cat',
                '/usr/sbin/blkid', '/usr/sbin/switch_root']
    if config is None: binaries.append('/usr/bin/uname')
    dependencies = closure(root, binaries)
    for name in sorted(dependencies | set(binaries)):
        copy_target(root, stage, name)
    shutil.copy2(ROOT/'src/initramfs'/('init-sd' if config is None else 'init'), stage/'init')
    (stage/'init').chmod(0o755)
    if config is not None:
        (stage/'etc/bpi-layout').write_text(f"ROOT_START={config['root_start']}\nROOT_SECTORS={config['root_sectors']}\nROOT_UUID={config['root_uuid']}\n")
    else:
        shutil.copy2(ROOT/'src/initramfs/sd-root.bash', stage/'etc/bpi-sd-root.bash')
    # Validate the actual composed runtime, including transitive loader inputs.
    for binary in binaries:
        run(runtime_command(stage, binary) + ['--version'], log=output.parent/('initrd-'+Path(binary).name+'.log'))
    run(runtime_command(stage, '/bin/bash') + ['-n', stage/'init'])
    if config is None:
        run(runtime_command(stage, '/bin/bash') + ['-n', stage/'etc/bpi-sd-root.bash'])
    output.write_bytes(gzip.compress(newc(stage), mtime=0))
    write_json(output.parent/'initramfs-manifest.json', {
        'recipe': 'source-controlled helper plus locked Fedora aarch64 executable/library closure',
        'inputs_sha256': {name: sha(target_path(root, name)) for name in sorted(dependencies)},
        'init_sha256': sha(stage/'init'), 'output_sha256': sha(output),
        'host_binaries_included': False, 'kernel_storage_filesystems': 'built-in SD and ext4'})
