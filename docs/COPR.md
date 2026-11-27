# Board kernel updates through COPR

The [common-image mode workflow](MODES.md) also builds install-only
`bpi-m4-kernel-media` from a self-contained SRPM via
`make srpm-kernel-media-updates`. The optional `bpi-m4-media` metapackage requires
that kernel and firmware/support/codec packages. These repository inputs and
native builds need validation before offering the complete Media installation;
the existing firmware redistribution review remains unresolved.

Fedora repositories supply userspace. A separate COPR project can supply the
board kernel without changing SPI for each kernel release. The existing
`bpi-m4-sd-boot` package activates versioned kernel bundles through extlinux;
it must already be installed on the board. See [KERNEL-UPDATES.md](KERNEL-UPDATES.md).

The initial COPR scope is `bpi-m4-kernel` in a native **fedora-45-aarch64**
chroot. The kernel contains the board SD, Ethernet and other selected drivers,
with matching modules. SPI firmware remains a separate hardware update.
The generic boot package's current build uses cross-binutils and QEMU; its
native COPR dependency path needs separate validation before adding it to the
project. An installed boot package is sufficient for kernel updates.

## Prepare and review a source package

```sh
make srpm-kernel-updates JOBS=8
jq -r '.srpms[0].sha256 + "  out/srpms/kernel-updates.src.rpm"' \
    out/srpms/kernel-updates.json | sha256sum --check --strict
rpm -qp --qf '%{NAME} %{VERSION}-%{RELEASE}\n' out/srpms/kernel-updates.src.rpm
rpm -qpl out/srpms/kernel-updates.src.rpm
```

`rpkg srpm` packages the pinned upstream source, local board inputs, patches,
release number and recipe identity. The SRPM is self-contained; COPR does not
need the checkout, local cache, vendor SDK compiler or a source download during
compilation. Local source preparation verifies the upstream kernel signature
and recorded hashes. Source identities are retained in the kernel's versioned
provenance file.

Increment `packaging/kernel-update-release` for every published build. A recipe
hash alone does not provide reliable RPM update ordering. The numeric release
and recipe hash also enter the kernel ABI, so matching modules and fallback
versions remain separate.

For the 2026-11-26 hardware update test, release 2 builds:

```text
bpi-m4-kernel-7.3.5-2.2d4edadf8d89.bpi_m4.fc45.aarch64
kernel ABI: 7.3.5-bpi_m4_fc_p10.r2.2d4edadf8d89
```

The local build passed in Mock with the same kernel source as the running
release-1 baseline. Its RPM SHA256 is
`25d70f5f6ba0eb9975d5857811a1ed59f2565e270bc6687a9785833af653a0e6`;
SRPM SHA256 is
`ec1ec6a1eb75b2d4d7c9e48e3d47b8d3b36018c5ee16af3a47d665096b382c79`.
These identify the retained local artifacts, not a future COPR rebuild.

The local release-2 RPM passed hardware installation, boot, release-1 fallback,
unused-release removal and reinstallation on the 2 GiB board. Three Linux
reboots passed with all four CPUs, verified boot files and wired networking.
The [SPI qualification record](hardware/spi-cpu-flash-2026-11-26.md) contains
the evidence. Public repository updates still require a native COPR build.

The kernel SPEC chooses native tools when the build host is aarch64. The local
Mock build used the x86_64 cross path. Native dependency selection was checked
with RPM parsing; an actual native COPR build remains necessary:

```sh
rpmspec -q --buildrequires --target aarch64 --without cross \
    --define "_sourcedir $PWD/work/rpms/kernel-updates/SOURCES" \
    work/rpms/kernel-updates/SOURCES/bpi-m4-kernel.spec
```

This selects ordinary `gcc` and `binutils`, with no cross-toolchain dependencies.

## Publish after hardware validation

Project creation and build submission publish to an external service. They
remain a later explicit approval step. Select the Fedora/COPR account and
project name before running these example commands with an authenticated
`copr-cli`:

```sh
copr-cli create --chroot fedora-45-aarch64 bpi-m4
copr-cli build bpi-m4 out/srpms/kernel-updates.src.rpm
```

The CLI is not installed on the current host; no project was created or build
submitted during preparation. Review the native build log and resulting RPM
architecture, kernel ABI, module hashes and package scriptlets before enabling
the repository on the board.

In the board's existing root UART shell, replacing `OWNER` with the approved
COPR account:

```sh
dnf install dnf5-plugins
dnf copr enable OWNER/bpi-m4
dnf upgrade bpi-m4-kernel
bpi-m4-bootctl list
bpi-m4-bootctl verify
```

Check activation errors before rebooting. The existing kernel remains installed
through DNF's install-only policy and the extlinux fallback menu. Hardware
validation must boot the new version, verify its modules/networking, select and
boot the previous version, then remove an unused version without losing a
working selection. Automatic failed-boot rollback is not implemented.
