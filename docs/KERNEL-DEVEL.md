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
