# Source provenance and licenses

New source is GPL-2.0-or-later unless a file states otherwise. Imported license
notices, copyright, patch authorship and sign-offs remain in their files.
See [LICENSE.md](../LICENSE.md), `licenses/GPL-2.0.txt` and
`licenses/Linux-COPYING`. Upstream sources and Fedora RPMs retain their own licenses.

## Retained board ports

Imports originate from the local PoC at revision
`288c47bc6a26feea7a54fc5535a62b03f4220434`. A complete vendor source tree is
not a build dependency for the existing SD images. The separate SPI target
archives the pinned BSP's `u-boot-rtk/` directory for retained early firmware and
packaging reference checks; SDK toolchains are excluded.

- `src/linux/mmc`: local GPL-2.0-only Realtek SD controller implementation.
  Protocol reference: BPI-SINOVOIP/BPI-M4-bsp revision
  `25f5b88ec4ba34029f964693dc34028b26e6c67c`.
- `src/linux/ethernet`: GPL-2.0-or-later r8169-derived Realtek platform port.
  Source notices retain ShuChen, Francois Romieu and other contributors.
- `src/linux/peripherals`: adapted clock, interrupt, eMMC and ACPU sources,
  attributed in `provenance.json` and `vendor-provenance.json`.
  `import-sha256.json` verifies retained imports during source preparation.
  Both USB reference patches are applied build inputs.
- `patches/linux/10-secondary-cpus.patch`: local RTD1395 spin-table/EL3 entry
  adaptation informed by JalenLin/BPI-W2-linux and Realtek's entry sequence.
- `patches/linux/20-sb2-barriers.patch`: JalenLin / Igor Pecovnik SB2 barrier
  changes with retained authorship and sign-offs.
- `patches/linux/30-watchdog-restart.patch`: an extension of the upstream
  RTD129x watchdog register protocol.
- `patches/linux/40-board-integration.patch`: local Kconfig/Kbuild registration
  and reserved-memory labels for the retained board ports.
- `src/linux/media/firmware-display.patch`: startup, RPC, picture-ring and
  scanout adaptations against the attributed imported ACPU driver.
- Automated controller tests retain locally developed PoC fault harnesses.

Radio firmware and regulatory data come from the signed Fedora RPM locks.

## U-Boot adaptations

`src/u-boot/sd.c` retains the required SD PLL, clock and pad sequence from
`rtk_sdmmc_init()` in the same GPL BSP's
`u-boot-rtk/drivers/mmc/rtksdmmc_rtd1395.c`.
Reference SHA-256:
`1f2092e562440092e69198c4079b272346fa8b9013002e96cc0a61d683843006`.

`src/u-boot/cpus.c` adapts the secondary-core release sequence from
`arch/arm/cpu/armv8/rtd1395/cpu.c` in that BSP. Copyright Tom Ting (2015) and
GPL-2.0-only remain in the file. Reference SHA-256:
`5ed1fb35e666905518ad2e6dfe00ce540f56a86929f4c2bfa2c68fc9d077de8a`.

`patches/u-boot/0002-use-32-bit-secondary-core-mailbox.patch` adapts the upstream ARMV8 holding pen to the
RTD1395 32-bit mailbox using the BSP's `arch/arm/cpu/armv8/start.S`.
Reference SHA-256:
`7bdb4c53dec4320247854fc28e1c000e965874b0e3ccd6bb7dcb0275c0eb31d3`.

These references document attribution; builds use the prepared upstream sources
and retained files. The existing SD loader does not need a separate BSP checkout.

`src/spi/sd-init.c` adapts cold SD initialization from the same RTD1395 driver;
`src/spi/lowlevel.S` adapts ACTLR/GIC entry setup from the same Realtek `start.S`.
Their Realtek attribution and GPL-2.0-only notices are retained. The SPI target
shares `sd.c`, `cpus.c` and the upstream mailbox patch with the SD loader.

`src/spi/spi-tools.c` implements the pinned packaging format using current
OpenSSL APIs. The mode-97 key derivation was reconstructed from the BSP's native
`obfuse_h` reference and verified against it inside Mock. `spi-layout.c` follows
the RTD1395 `bindAllBins.c` layout and is compared with the rebuilt reference.
Vendor Perl RSA formatting and native-host reference generators are confined to
build comparisons, not shipped as runtime helpers. See [SPI-BOOT.md](SPI-BOOT.md)
for pinned identities, retained firmware hashes and format details.

The SPI RPM additionally contains the pinned vendor ARM/MIPS ROM and encrypted
FSBL blobs. The BSP does not establish their separate redistribution terms;
`LicenseRef-Realtek-Firmware` records that unresolved part of this local research
package. Do not infer public firmware distribution rights from a successful build.

## Downloaded components

Linux and U-Boot retain their upstream source notices and licenses. Their exact
source/signature identities for SD builds are in the profile locks. The separate
SPI source uses the official pinned U-Boot v2027.01-rc3 Git commit and local
archive hashes described in [SPI-BOOT.md](SPI-BOOT.md), without claiming release
signature verification. Fedora packages retain
their own licenses.

The private FFmpeg decoder is LGPL-2.1-or-later; see [codec provenance](MEDIA-CODECS.md).
The vendor display firmware has separate distribution terms; see
[firmware provenance](MEDIA-FIRMWARE.md). Packaging a binary does not establish
redistribution permission.
