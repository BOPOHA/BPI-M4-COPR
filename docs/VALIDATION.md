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

COPR Git pull migration, 2026-11-27

All seven package defaults now use Git SCM, main, and make_srpm from
https://github.com/BOPOHA/BPI-M4-COPR.git. COPR-SCM-2026-11-27.json records live
settings verified against packaging/copr-scm.json. Webhook builds remain off.
The source worker prepares self-contained SRPMs; native fedora-45-aarch64
buildroots compile them. Local SRPM and Mock cross paths remain supported.

Twenty Python regressions and the eMMC clock guard passed in regular-user Mock.
Server and Media source-only preparation produced the expected kernel SRPMs,
without compiling a kernel. Board source recipe identity matched between the
laptop and the cold COPR source worker. The source worker uses Fedora 44 and the
checked-in, fingerprint-verified Fedora 45 key for target RPM verification.

A fresh-source GnuPG home assumption initially failed boot/codec preparation.
Key fingerprint checks now use isolated temporary GnuPG homes; the new regression
verifies that an absent user keyring is neither needed nor created. Corrected
cold-source preparation and native ARM64 pull builds passed:

- Board support: 11399711
- SD boot: 11399860
- Native codecs and ABI audit: 11399861
- Updated regressions: 11399862 (earlier pull checks also passed as 11399785)
- Exact pinned native kernel-devel module checks: 11399786

COPR-PULL-VALIDATION-2026-11-27.json records successful public API states and the
recovered source failures. COPR-PULL.md documents UI fields, configuration and
build-package commands. Kernel package defaults are configured and both source
profiles were verified; kernels were not recompiled for this migration. Firmware
publication, hardware qualification and the IMAGE package lock remain separate.
No host package installation, device write or hardware boot was performed.

Kernel Git pull monitoring and SRPM cleanup, 2026-11-27

The user-triggered native ARM64 kernel build 11399885 succeeded without a kernel
fix. Redundant copr_source.py orchestration was replaced with scripts/copr-srpm.bash;
package routing lives in packaging/copr-scm.json. Unused image-era DNF helpers
and the unused --request option were removed. Twenty Python regressions and the
eMMC guard passed in regular-user Mock; Bash-source board and regression pull
builds 11399894/11399895 also succeeded. Both source paths preserve native ARM64
and laptop cross options.

The requested rerun from the Bash entry point succeeded as 11399915. Kernel update
revision 6 ensures the changed recipe sorts after revision 5. Published ABI:
7.3.5-bpi_m4_fc_p10.r6.91b4dc2cb76e

The native devel RPM signature was verified with the pinned COPR key. Its SHA256
and exact ABI now populate inputs.module-check.lock.json. Native pull build
11399962 passed the exact make -C TREE M=MODULE modules check against that RPM,
including the internal MMC card header and matching vermagic, without ARCH,
CROSS_COMPILE or LOCALVERSION overrides and without recompiling Linux.

KERNEL-PULL-VALIDATION-2026-11-27.json records the successful public API states,
devel signature verification and artifact pins. No kernel was compiled on the
laptop, installed on the host or flashed to hardware. The IMAGE lock and
historical fc checkout are unchanged; hardware boot remains unqualified.
