Native aarch64 update builds produce bpi-m4-kernel-devel or
bpi-m4-kernel-media-devel from the exact kernel build. Cross builds omit devel
because their executable build helpers target x86_64. Native %check compiles
an external module against the staged packaged tree and checks vermagic.
Native COPR execution and installation on the board are still required.

```sh
dnf install "kernel-devel-uname-r = $(uname -r)" gcc make
make -C "/usr/lib/modules/$(uname -r)/build" M="$PWD" modules
```

Installation is operator-controlled. Keep fallback ABI versions installed.

The optional `make srpm-module-checks` prepares a build-only SRPM from a pinned,
signature-verified published native development RPM. Its native COPR test uses
`make -C TREE M=MODULE modules` with no ARCH/CROSS_COMPILE/LOCALVERSION overrides,
checks matching vermagic, and includes the eMMC internal header. It does not
compile Linux or install a kernel on the host. Pins are in
inputs.module-check.lock.json. Submit out/srpms/module-checks.src.rpm to the
native fedora-45-aarch64 chroot. This test artifact is not an image dependency.
