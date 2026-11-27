Native ARM64 builder and repository host:
https://copr.fedorainfracloud.org/coprs/vorona/bpi-m4/
Git sources: https://github.com/BOPOHA/BPI-M4-COPR

Server submissions (fedora-45-aarch64):
- 11396974: board-support (includes optional Media support/metapackage)
- 11396975: generic sd-boot (native build succeeded)
- 11396976: Server kernel release 5 and matching native kernel-devel
- 11396990: optional Media kernel and matching native kernel-devel
- 11396991: optional native codecs (no vendor firmware submitted)
- 11397005: external-module check against the published Server devel RPM

All listed native builds succeeded.

Local x86_64 Mock runs validate source extraction with cross tools. COPR is the
native aarch64 builder and package repository. The redundant laptop kernel
build was canceled; it is not the release artifact source.

Do not upload vendor firmware until redistribution rights are resolved.
Native Media kernel/codecs need their own qualification. The default image
uses only Server packages and does not install devel or SPI artifacts.

Source archives are self-contained; downstream COPR builds perform no network
source fetches. The image repository refreshes its lock using successful native
build IDs, signed RPMs, package hashes and the actual COPR key.
