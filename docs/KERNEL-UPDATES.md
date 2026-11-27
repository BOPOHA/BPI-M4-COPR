# Versioned kernels and SD boot updates

This path targets the modern SPI U-Boot described in [SPI-BOOT.md](SPI-BOOT.md).
The common image defaults to Server and can install/select Media on the same
root filesystem; see [MODES.md](MODES.md).
Stage 4 builds updateable board-kernel RPMs and a kernel-independent initramfs,
installs complete boot bundles and selects them through extlinux. The
[2026-11-26 hardware test](hardware/spi-cpu-flash-2026-11-26.md) verified kernel
installation, fallback, unused-version removal and reinstallation on the 2 GiB
board. COPR publishing remains a later approval stage.

## Build

```sh
make rpm-kernel-updates rpm-sd-boot JOBS=8
make image JOBS=8
```

SRPMs are `out/srpms/{kernel-updates,sd-boot}.src.rpm`; binary aliases and
integrity receipts are under `out/rpms`. `SPI_SD_OUTPUT=path` selects a custom
test image. Make reuses unchanged packages and images.

The Server update package is `bpi-m4-kernel`; the Media update package is
`bpi-m4-kernel-media`. Both provide `installonlypkg(kernel)` and `kernel-uname-r`, so
Fedora DNF retains multiple versions and protects the running kernel. DNF's
default install-only limit is three. Legacy SD-image recipes remain available
through the explicit legacy targets.

`packaging/kernel-update-release` is a positive, monotonically increasing RPM
release number. Increment it for each published kernel build, including patches
to the same upstream kernel version. The kernel ABI additionally includes the
recipe hash, so different builds cannot overwrite one another's modules.
Changing only a recipe hash does not establish a monotonically ordered update;
publishing still requires a release-number increment. Upstream kernel upgrades
also require source lock/spec version updates and compatibility checks.

Sources are packaged into self-contained SRPMs with rpkg; compilation happens
in Mock. `make srpm-kernel-updates` and `make srpm-sd-boot` prepare source-only
products. The kernel SPEC selects native tools on an aarch64 build host and cross
tools on x86_64. `--without cross` explicitly selects the native path; aarch64 RPM
target validation prevents accidental packaging for x86_64. Future COPR builds
should use a native aarch64 chroot. The native dependency path is checked by RPM
parsing; the compiled local result uses Fedora x86_64 cross tools. COPR
configuration and public submission are not part of these commands.

## Update contract

The kernel RPM owns matching modules and immutable sources under
`/usr/lib/bpi-m4/kernels/RELEASE/`. The `bpi-m4-sd-boot` RPM owns the generic
target-Fedora initramfs and `/usr/sbin/bpi-m4-bootctl`. Its initramfs has built-in
SD/ext4 support through the board kernel and needs no per-kernel driver modules.
It discovers the root via the loader's PARTUUID, rejects ambiguous/non-SD roots,
and verifies the kernel's actual CID, capacity and partition write limits before
mounting ext4. It also requires matching installed modules for the running kernel.

After a kernel transaction, `bpi-m4-bootctl add RELEASE` checks packaged source
hashes and creates `/boot/bpi-m4/RELEASE/{Image,initramfs.img,board.dtb,SHA256SUMS}`.
It checks the complete bundle and flushes it before atomically updating
`/boot/extlinux/extlinux.conf`. Existing bundles retain their own initramfs copies
when the generic initramfs RPM is updated. No FAT partition or SPI firmware is
changed. A failed activation leaves the previous menu in place; RPM installation
itself can still have completed, so review DNF scriptlet failures before rebooting.

The generic initramfs is a snapshot of locked, signature-verified Fedora runtime
packages. Userspace DNF updates do not regenerate it. Maintainers refresh its
runtime inputs and bump the boot RPM's Version or numeric Release prefix when
shipping a new snapshot; newly installed kernel bundles then capture it. Older
fallback bundles keep their previous snapshot.

Each kernel source/bundle includes a checksum-covered `boot-profile`. Updates
advance only the selected mode; installing Media does not change Server's
default. `bpi-m4-mode server|media` selects the newest complete bundle of that
mode and requests a physical power cycle. Media selection requires its packages
and a loader advertising the secure handoff. Earlier SPI kernels without a
profile record are treated as Server for compatibility.

Older entries remain available for manual fallback. Removing a kernel updates
the menu before deleting its boot bundle and refuses to remove the last entry
or the running kernel, and preserves at least one Server kernel. An unmanaged extlinux configuration is preserved and
causes activation to fail for operator review. An optional one-line
`/etc/bpi-m4/kernel-args` supplies extra kernel arguments.
RPM transaction markers preserve the incoming ABI during reinstall without
skipping cleanup of other installed kernel versions.

On the board, the operator runs privileged update/selection commands manually:

```sh
sudo dnf upgrade
sudo bpi-m4-bootctl verify
bpi-m4-bootctl list
sudo bpi-m4-bootctl set-default RELEASE
```

This provides manual version fallback, not automatic failed-boot rollback or an
atomic Fedora IoT/OSTree userspace update. Fedora repositories update userspace;
a future approved COPR repository can supply the board kernel. SPI firmware stays
independent of kernel version, card identity and root partition size.

## Test SD image

`out/fedora-bpi-m4.raw` is the common image for modern SPI boot. The
ext4 root contains `/boot` and the managed extlinux menu. The FAT partition holds
`u-boot-spi.bin` for a later approved RAM-loader test; it does not provide the
image-specific second-stage file expected by the old vendor `gosdb` path.
Build the SPI candidate with `make spi SPI_DRAM_GIB=2` first. Do not expect this
test image to boot automatically through the unchanged old SPI loader.

The latest profile-aware SPI candidate validates the OS device tree's memory
contract and prepares Media's secure startup flag. The hardware record below
qualifies the earlier Server loader; the new Media handoff needs validation.

Hardware validation for subsequent builds must check the UART banner, selected
release, SD root, matching modules, networking, installation of a second release, fallback
selection and removal of an unused release. No physical flashing is performed
by the stage-4 build targets.

## Hardware update validation

On 2026-11-26, the updated physical SPI loader passed three cold boots and
three Linux reboots with all four CPUs. DNF co-installed release 2 beside
release 1 and selected its complete boot bundle. Release 2 booted successfully;
explicitly selecting release 1 then rebooting verified fallback. While running
release 1, DNF removed the unused release 2 without changing release 1's files
or selection. Reinstalling release 2 restored both entries and its default;
the third reboot ran release 2. Both installed RPMs passed `rpm -V`.

The new ABI is `7.3.5-bpi_m4_fc_p10.r2.2d4edadf8d89`; the baseline is
`7.3.5-bpi_m4_fc_p10.r1.fdc85ca9b5a0`. The source is unchanged between these
builds: the incremented numeric release tests update ordering and ABI separation.
The 1 GiB root retained 252 MiB free after the complete test. No partition
expansion or firmware write was required for kernel transactions.

These tests installed a SHA256-verified local RPM with DNF repositories disabled,
using the authorized root UART shell. They validate the package lifecycle;
native COPR compilation and public repository updates remain separate work.
See the [hardware record and evidence](hardware/spi-cpu-flash-2026-11-26.md) and
[COPR preparation](COPR.md).

## Host validation

The stage-4 Mock regression run passed 51 checks, including actual kernel scriptlet
installation, reinstall and removal through small private RPM fixtures. Tests
also cover concurrent activation, corrupted source/bundle files, unmanaged
configuration preservation, manual fallback, last-entry protection and detected
SD identity/write-bound checks. These fixtures test the update lifecycle, not
Linux execution on the board. QEMU validates the composed aarch64 initramfs
executables and Bash syntax; the physical Realtek hardware is not emulated.

The later CPU-fix development run passed 50 of 51 test methods. The flash-default
method failed three subcases because the local, uncommitted Makefile selects
SPI image names while those tests expect legacy server/media names. The
[hardware qualification record](hardware/spi-cpu-flash-2026-11-26.md) records
this test limitation separately from the successful SPI and RPM hardware checks.
