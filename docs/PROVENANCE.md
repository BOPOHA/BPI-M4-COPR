# Source provenance and licenses

New source is GPL-2.0-or-later unless a file states otherwise. Imported license
notices, copyright, patch authorship and sign-offs remain in their files.
See [LICENSE.md](../LICENSE.md), `licenses/GPL-2.0.txt` and
`licenses/Linux-COPYING`. Upstream sources and Fedora RPMs retain their own licenses.

## Retained board ports

Imports originate from the local PoC at revision
`288c47bc6a26feea7a54fc5535a62b03f4220434`. Builds need no vendor checkout; retained driver provenance and hashes are
kept beside the imported files.

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

## Downloaded components

Linux sources and signatures are pinned in inputs.kernel.lock.json. Initramfs
runtime RPMs and codec sources/sysroot RPMs are pinned in their respective locks.
Fedora inputs retain their own licenses. The private FFmpeg decoder remains
LGPL-2.1-or-later; see [MEDIA-CODECS.md](MEDIA-CODECS.md). Vendor firmware rights
remain unresolved; see [MEDIA-FIRMWARE.md](MEDIA-FIRMWARE.md).
