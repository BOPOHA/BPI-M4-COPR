Independent extraction validation, 2026-11-27

15 OS/package regression tests and the eMMC clock guard passed in fresh local
Mock. Kernel/boot/codec SPECs support native ARM64 and x86_64 cross builds.
Native COPR builds succeeded for board-support (11396974), generic boot
(11396975), Server kernel/devel (11396976), Media kernel/devel (11396990), and
codecs (11396991). The redundant laptop kernel build was canceled.

The additional native test 11397005 compiled a small external module from the
published development RPM, including the eMMC internal header, using the exact
operator make command with no ARCH/CROSS_COMPILE/LOCALVERSION override. Matching
vermagic passed without a Linux rebuild. NATIVE-DEVEL-AUDIT-2026-11-27.json
records packaged ARM64 helpers, configuration, symbols and required headers.
COPR-BUILDS-2026-11-27.json records public build identities/status.

Vendor firmware was not submitted; redistribution remains unqualified. Native
compilation does not qualify Media output, eMMC writes or new hardware boots.
No kernel or module was installed onto the operator's laptop or board.

Python tooling review, 2026-11-27

Renamed bpi_image to bpi_packaging in imports, Make targets, SPEC invocations,
source recipe identities and self-contained SRPM payloads. Removed unused
imports, including YAML, and removed the PyYAML host/checks dependency.
The target dependency resolver, binary audits and controller tests remain Python.

Regular-user make checks passed in Mock: 15 Python regressions and the compiled
eMMC clock guard. Local make test lacked a C compiler; Mock supplied it without
host package installation. Affected SRPM archives contain bpi_packaging and no
bpi_image package paths. Native fedora-45-aarch64 COPR validation also passed:

- SD boot: https://copr.fedorainfracloud.org/coprs/build/11399641
- Native codecs, including ABI audit: https://copr.fedorainfracloud.org/coprs/build/11399642

COPR-BUILDS-2026-11-27.json records their successful public API states. See
PYTHON-TOOLING.md for retained Python roles and namespace migration. No kernel
was rebuilt or installed, no IMAGE input lock changed, and no hardware was flashed.
