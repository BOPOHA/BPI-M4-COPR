# COPR build workflow

COPR pulls this repository using the defaults in packaging/copr-scm.json,
prepares an SRPM with make_srpm, and compiles on fedora-45-aarch64. COPR also
hosts the resulting RPM repository. See [Git pull configuration](COPR-PULL.md).

```sh
make configure
make build PACKAGE=bpi-m4-kernel
make build PACKAGE=bpi-m4-kernel-media
make checks
```

There are no local SRPM, binary RPM or Mock build targets. GitHub Actions can
request the same COPR build-package operation; its trigger is maintained by
the operator.

The kernel, sd-boot and codec SPECs retain `%bcond cross`: aarch64 defaults to
native tools, and other architectures default to cross tools. The rpmbuild and
rpmspec overrides remain `--with cross` and `--without cross`. This is a SPEC
capability, not a supported local build workflow. Cross kernel builds omit the
devel RPM because their executable helpers target the build host. Native boot
checks execute the staged ARM64 loader and libraries without chroot or QEMU.

All kernels use immutable versioned bundles and retain fallback handling.
Increment packaging/kernel-update-release before publishing a changed kernel
recipe. Review the module-check and IMAGE locks before selecting a new ABI.
No build command flashes or qualifies hardware.
