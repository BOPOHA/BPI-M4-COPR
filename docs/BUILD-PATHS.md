# Native ARM64 and laptop cross builds

The kernel, sd-boot and native-codecs SPECs use `%bcond cross`.
The default checks `%{_host_cpu}`: aarch64 uses native tools; an x86_64 host
uses cross tools. The same self-contained SRPM supports both paths without
changing source/configuration pins or its kernel ABI. COPR is the native ARM64
release builder and repository host. Local Mock is available when COPR is down.

COPR releases pull Git sources using the package defaults in
packaging/copr-scm.json. See [Git pull configuration](COPR-PULL.md). For example:

```sh
copr-cli build-package --nowait -r fedora-45-aarch64 --name bpi-m4-kernel vorona/bpi-m4
```

Laptop development:

```sh
make srpm-kernel-updates
make rpm-kernel-updates JOBS=8
make checks
```

Explicit cross override, run as regular user:

```sh
/usr/bin/mock -r packaging/mock/bpi-m4-f45-cross.cfg --define '_with_cross 1' --rebuild out/srpms/kernel-updates.src.rpm
```

On an ARM64 build host, explicit native override:

```sh
/usr/bin/mock -r fedora-45-aarch64 --define '_without_cross 1' --rebuild out/srpms/kernel-updates.src.rpm
```

The equivalent rpmbuild/rpmspec flags are `--with cross` and `--without cross`.
Forcing native on x86_64 does not supply an ARM64 compiler or execution host.
Native devel RPMs include native ARM64 Kbuild helpers. Cross builds intentionally
omit the devel subpackage because their executable helpers target x86_64;
the cross path still produces matching kernel/DTB/modules and tests their ABI.
Server and Media use the same toggle. Boot's native checks execute the staged
ARM64 dynamic loader with the staged libraries, without chroot or QEMU.

Increment packaging/kernel-update-release before every new published recipe;
keep the working fallback installed. No build command flashes a device.
