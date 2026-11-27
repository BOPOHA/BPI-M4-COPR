# Native external-module development

Native COPR kernels provide bpi-m4-kernel-devel or bpi-m4-kernel-media-devel
for the exact ABI. Cross builds omit devel because executable build helpers
would target the build host. Native kernel checks build a module against the
staged tree and verify vermagic.

On the board, install matching development tools manually:

```sh
sudo dnf install "kernel-devel-uname-r = $(uname -r)" gcc make
make -C "/usr/lib/modules/$(uname -r)/build" M="$PWD" modules
```

Keep fallback ABIs installed. `make build PACKAGE=bpi-m4-module-checks` requests
a native COPR Git pull check against inputs.module-check.lock.json. The source
worker verifies the pinned devel RPM signature/hash and checks its exact ABI.
The build uses make -C TREE M=MODULE modules without cross/architecture/version
overrides and includes the internal MMC header. It never recompiles Linux or
installs a host kernel. See [VALIDATION.md](VALIDATION.md).
