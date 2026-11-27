Current workflow: COPR Git pull is the only supported build interface.
Local SRPM uploads and Mock targets below describe historical work and are
retired. Use [BUILD-PATHS.md](BUILD-PATHS.md) for current build commands; image
and SPI builds belong to the independent BPI-M4-IMAGE and BPI-M4-SPI repositories.

# Media firmware source and startup

The media profile uses the RTD1395 BSP's `bluecore.audio` on the audio CPU
(ACPU), which also controls the output mixer and HDMI transmitter used by the
DRM driver. Server includes no copy and does not launch it. This blob supplies
display RPC, not an implemented Linux hardware video decoder.

The common image installs no media firmware by default. `dnf install
bpi-m4-media` adds its kernel and firmware/support/player packages;
`bpi-m4-mode media` selects that boot bundle for a physical power cycle.
The profile-aware SPI candidate performs the early secure handoff and leaves
firmware loading to Linux. See [MODES.md](MODES.md). The new path still requires
Media hardware qualification.

## Exact download

- Repository: [BPI-SINOVOIP/BPI-M4-bsp](https://github.com/BPI-SINOVOIP/BPI-M4-bsp).
- Commit: `25f5b88ec4ba34029f964693dc34028b26e6c67c`.
- [bluecore.audio](https://raw.githubusercontent.com/BPI-SINOVOIP/BPI-M4-bsp/25f5b88ec4ba34029f964693dc34028b26e6c67c/rtk-pack/rtk/bpi-m4/configs/default/linux/bluecore.audio).
- Size: 4,319,769 bytes.
- SHA-256: `774832da0a18c1ba837ff41926502fb8444e83397562c7170c71435416aff4df`.

[config/media-firmware.json](../config/media-firmware.json) pins URL, size and
digest. The firmware SPEC declares the immutable URL as `Source0`; `rpkg srpm`
uses RPM's source-fetch capability when verified cached bytes are unavailable.
The source stage checks the hash and size, and the SPEC's native `%prep` checks
hash, size, load-area bounds and provenance before installation. Verified bytes
are cached under ignored `cache/firmware/`. Mock packages them separately as `bpi-m4-media-firmware` at
`/usr/lib/firmware/realtek/rtd1395/bluecore.audio` on root p2. The image manifest
records its provenance. It is owned by a local hash-checked RPM, not a
Fedora-signed input. `make srpm-firmware` emits the SRPM containing the blob;
`make rpm-firmware` prepares that SRPM and rebuilds it with Mock;
both remain local artifacts. Redistribution rights are not established; check
the upstream distribution terms before sharing the firmware or its RPM/SRPM.

The vendor `.enc.A01`, `uInitrd`, `uEnv.txt` and U-Boot binary are not build
inputs. The SD loader, kernel and initramfs are source-built here. Existing
onboard SPI/DDR initialization remains a separate required dependency.

## Startup contract

The common SPI loader verifies inactive media state and reserved-memory layout,
arms/readbacks the EL3 secure startup flag, leaves the ACPU clock off, and
records a fresh handoff in `/chosen`. Linux verifies the exact firmware size/hash
when explicitly loading it. The legacy SD loader also verifies the blob before
handoff. One-step boot display is deferred. Ordinary Fedora boot keeps
ACPU loading blacklisted and activation parameters false.

```sh
sudo bpi-m4-hdmi-start
```

Explicit activation validates the handoff, firmware size/hash, reserved-memory
layout and inactive RPC state. Linux loads firmware and prepares bounded rings
and IRQ handling before releasing the ACPU clock. Bounded RPC
readiness and the RTD1395 RGB/SDR HDMI configuration precede VO creation.
The helper waits for the asynchronous DRM probe and refuses to relaunch an
already loaded firmware driver. Startup follows the pinned RTD1395 BSP's
`common/cmd_boot.c:do_go_audio_fw()`, `system.h`, `rtk_ipc_shm.h` and logo/RPC
TV-system structures; no newer SoC register sequence is assumed.

The firmware and owned ring/scanout resources remain pinned while running.
After a failed or uncertain launch, physically cold boot before retrying;
module unloading cannot reset the independent processor. Successful RPC,
DRM creation, command consumption and visible output are distinct checks.
