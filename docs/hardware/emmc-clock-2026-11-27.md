# eMMC clock handoff fix

Board: original Banana Pi M4 / RTD1395, 2 GiB RAM. On 2026-11-27 the board
was running Server kernel `7.3.5-bpi_m4_fc_p10.r3.6c39798f43c8` from SD with
four CPUs. The 2 GiB root partition had 1.3 GiB free before diagnostics. UART
provided the existing root shell; SSH staging used the unprivileged `fedora`
account at `192.168.1.241`. No host `sudo`, SPI programming or eMMC writes were
used.

## Diagnosis

The [release-3 failure](common-server-2026-11-27.md) was reproducible:

```text
rtd129x-emmc 98012000.mmc: error -22: Unverified inherited eMMC clock
```

A temporary read-only module, built in Mock against the running kernel's
configuration and symbols, read the handoff registers:

| Register | Value | Meaning |
| --- | --- | --- |
| CRT PLL_EMMC1 `0x980001f0` | `00000003` | PLL reset released; firmware phases retained |
| CRT PLL_EMMC3 `0x980001f8` | `00464388` | Vendor 80 MHz frequency code `0x46` |
| CRT PLL_EMMC4 `0x980001fc` | `00000007` | PLL output enabled |
| eMMC CKGEN `0x98012478` | `00002100` | PLL source, wrapper divider bypassed |
| eMMC VERID `0x9801206c` | `5342290a` | Expected controller identity |
| eMMC HCON `0x98012070` | `00c46d41` | Expected controller configuration |

The retained early firmware already supplies a usable 80 MHz clock. The
driver incorrectly required the vendor U-Boot's later 200 MHz setting. Merely
assuming 200 MHz would also calculate the wrong card-clock divider.

The pinned vendor BSP's Linux `rtkemmc_set_freq()` documents codes `0x46`
(80 MHz), `0x57` (100 MHz) and `0xa6` (200 MHz). Source provenance remains
`25f5b88ec4ba34029f964693dc34028b26e6c67c`,
`linux-rtk/drivers/mmc/host/rtkemmc.c`. The local patch
`patches/linux/50-emmc-clock-handoff.patch` validates those three rates, the
analog settings, PLL reset/output state and wrapper clock source, then uses
the verified rate for card-clock division. Unknown settings still fail before
controller writes, with the relevant register values in the error message.
PLL programming, pad-voltage changes and phase tuning are unnecessary for
this board's observed handoff.

Pristine imported sources and their hash receipt remain unchanged. The kernel
SPEC applies this patch after importing and authenticating the source.

## Module-only hardware test

The patched module was compiled with current Fedora tools in regular-user
Mock, using the release-3 configuration and `Module.symvers`. Its vermagic was
`7.3.5-bpi_m4_fc_p10.r3.6c39798f43c8 SMP preempt mod_unload aarch64`, and its
SHA256 was `bb93a3b8f47da63622b51c66b1e7d8237a2fe0131bc56b2c4858753f765b8a40`.
Only the `.ko` was transferred to `/var/tmp/`; no kernel was built on the board.
After unloading the failed original module, the root UART shell loaded this
temporary module with `activate=1`:

```text
rtd129x-emmc 98012000.mmc: inherited eMMC clock 80 MHz (PLL 00464388)
rtd129x-emmc 98012000.mmc: RTD129x eMMC (DW MSHC 290a), 80 MHz PLL
mmc1: new MMC card at address 0001
mmcblk1: mmc1:0001 8GTF4R 7.28 GiB (ro)
```

`lsblk -b` and `blockdev --getsize64` confirmed 7,818,182,656 bytes;
`blockdev --getro` returned `1`. CID:
`150100384754463452067cbd8cc79813`. The block device exposed no partitions.
The existing read-only driver policy remains in force: one-bit legacy timing,
at most 20 MHz, at most one page per read, no user-data writes or partition
switching, and no boot-partition exposure.

Two direct reads of the first 16 MiB and two of the last 16 MiB used:

```sh
dd if=/dev/mmcblk1 of=/var/tmp/emmc-head-a.bin bs=4096 count=4096 \
    iflag=direct,fullblock status=progress
dd if=/dev/mmcblk1 of=/var/tmp/emmc-tail-a.bin bs=4096 \
    skip=$((7818182656 / 4096 - 4096)) count=4096 \
    iflag=direct,fullblock status=progress
```

Each command was repeated with the corresponding `-b.bin` output. Every read
returned exactly 16,777,216 bytes, at approximately 2.2 MB/s. Pairwise SHA256
results matched:

- First 16 MiB: `9556b2e678558756a7121ce5eb2363418a4e70fa116fbf3b78cecdd3da86296f`.
- Last 16 MiB: `080acf35a507ac9849cfcba47dc2ad83e01b75663a516279c8b9d243b719643e`.

No eMMC error appeared in the log after these reads. CPUs remained `0-3`, and
boot ID remained `d27d2c41-3a5b-4d4d-ad17-869001b2741c`. Loading the temporary
out-of-tree diagnostic/module tainted this test boot. Raw output is retained
locally in `work/emmc-uart-20261127.log`; it is not a portable tracked artifact.

## Host regression checks

`make test JOBS=8` passed in Mock: the new native C clock guard harness plus
all 55 existing Python regression tests. The harness compiles the actual
patched function and checks the three supported rates, unknown frequency and
analog settings, PLL reset/output state, alternate wrapper clocks, and each
regmap read error. `tests/check-emmc-clock.bash` does not access hardware.

These tests qualify enumeration and bounded reads on the observed handoff.
Writable eMMC, higher bus widths/speeds, sustained I/O and booting from eMMC
remain separate work. SPI still needs an eMMC reader for booting from that
storage; this Linux fix alone does not add it.

## Persistent kernel build

`make rpm-kernel-updates JOBS=8` built release 4 in Mock, with the complete
kernel/modules/DTB package checks passing. The existing source version remains
7.3.5; the numeric RPM release advances so DNF ordering and kernel ABI remain
separate from release 3.

- Kernel ABI: `7.3.5-bpi_m4_fc_p10.r4.6dd0c134e3bb`.
- RPM: `out/rpms/bpi-m4-kernel-7.3.5-4.6dd0c134e3bb.bpi_m4.fc45.aarch64.rpm`.
- RPM SHA256: `a59bca722520adc1c48c67518c244e96ba8c8cbd7b47d1177b32ac88a752df42`.
- SRPM SHA256: `3a683c212bc8a3735c395c97c1a1a7adbdbd9de6a30249467aecc6f8a7e93c9e`.
- Packaged eMMC module SHA256: `05cac0a01510ae633f053e0088e785238596c841a7f3c02eddbe1774b1e71f21`.

The RPM was extracted on the host to verify its eMMC module's new ABI and
clock diagnostics, then transferred over SSH; the UART shell confirmed its
SHA256. It contains about 16.4 MB of installed files, and the board still had
1.2 GiB free before installation. Neither a new SPI build nor an SD flash is
needed for this kernel update.

DNF installed release 4 alongside release 3 and successfully activated its
complete boot bundle. Both bundles passed `bpi-m4-bootctl verify`, and
`rpm -V bpi-m4-kernel` reported no differences. A Linux reboot then reached
release 4 through the same modern SPI loader, with eMMC detected automatically:

```text
Linux version 7.3.5-bpi_m4_fc_p10.r4.6dd0c134e3bb
rtd129x-emmc 98012000.mmc: inherited eMMC clock 80 MHz (PLL 00464388)
mmc1: new MMC card at address 0001
mmcblk1: mmc1:0001 8GTF4R 7.28 GiB (ro)
```

The new boot ID was `f9dd94b7-e10b-4d98-b7f9-63b6e622c915`. Root remained on
SD p2; eMMC capacity/read-only state were unchanged. CPUs were `0-3`, RAM was
1.9 GiB, kernel taint was `0`, and SSH plus running/next Server mode status
worked. No temporary diagnostic module was loaded in this boot. Release 3
remains installed as fallback. The saved host common image still contains
release 3; no image rebuild or physical SD flash occurred during this fix.

Direct reads of the first and last 16 MiB were repeated with the packaged
release-4 driver after reboot. Both returned exactly 16,777,216 bytes and
matched the respective hashes above (about 2.2 MB/s). No eMMC errors appeared
in the new boot's log, the boot ID stayed unchanged, and kernel RPM verification
passed again. Temporary raw read files and diagnostic modules were then removed
from `/var/tmp/`; the verified kernel RPM was retained there.

The preceding shutdown exposed a separate pilot-policy limitation:
`mmc1: Power Off Notification timed out, 600` / `error -74 during shutdown`.
The existing command whitelist accepts the initialization value `1` for
`EXT_CSD_POWER_OFF_NOTIFICATION`, but rejects the later short/long shutdown
notification values. The SD root was remounted read-only before reboot, and
the reboot completed successfully. This warning does not establish an eMMC
data-transfer failure, but shutdown notifications must be corrected and
qualified before writable eMMC or power-management support is offered.
