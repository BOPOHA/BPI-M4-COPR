# Versioned kernel updates

Build kernels and generic boot support through COPR Git pull:

```sh
make build PACKAGE=bpi-m4-kernel
make build PACKAGE=bpi-m4-kernel-media
make build PACKAGE=bpi-m4-sd-boot
```

Image assembly belongs to BPI-M4-IMAGE; SPI firmware belongs to BPI-M4-SPI.
Increment packaging/kernel-update-release for each published kernel recipe.
Its numeric revision establishes RPM ordering, while the recipe hash gives
separate kernel ABIs. Source/spec upgrades require matching input lock updates.

Server and Media kernels provide installonlypkg(kernel) and kernel-uname-r.
DNF retains multiple versions and protects the running kernel. The kernel owns
immutable /usr/lib/bpi-m4/kernels/RELEASE sources and matching modules. Generic
bpi-m4-sd-boot owns the initramfs and /usr/sbin/bpi-m4-bootctl.

The initramfs discovers the SD root via PARTUUID, verifies CID/capacity/write
bounds and matching modules, and mounts ext4. Its executable/library closure
comes from locked signed Fedora RPMs. Refreshing userspace does not regenerate
this snapshot; changes require reviewed boot inputs and a new package release.

After installation, bootctl validates packaged hashes and creates complete
/boot/bpi-m4/RELEASE bundles before atomically updating extlinux.conf. Older
bundles retain their initramfs snapshot. Failed activation preserves the prior
menu. Review DNF scriptlet errors before rebooting.

Mode selection remains unchanged when installing another profile. Selected-mode
updates advance to the newest complete bundle. Removal refuses the last entry,
the running kernel and the last Server kernel. Reinstall transaction markers
preserve the incoming ABI. Unmanaged extlinux configurations are preserved and
block automatic activation. /etc/bpi-m4/kernel-args can supply extra arguments.

On the board, run privileged update and selection commands manually:

```sh
sudo dnf upgrade
sudo bpi-m4-bootctl verify
bpi-m4-bootctl list
sudo bpi-m4-bootctl set-default RELEASE
```

Keep a working fallback. Switching modes requires physical power cycling.
Earlier installed SPI bundles without boot-profile remain compatible as Server.
Automatic failed-boot rollback is not implemented. Kernel transactions do not
write SPI, repartition SD or reboot the board. See [MODES.md](MODES.md),
[KERNEL-DEVEL.md](KERNEL-DEVEL.md) and [VALIDATION.md](VALIDATION.md).
