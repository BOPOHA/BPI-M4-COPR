# Server and Media modes

The independent BPI-M4-IMAGE repository assembles a Server image from signed
RPMs. Server and Media share its ext4 root, accounts and application data.

| Mode | Kernel | Usable RAM on a 2 GiB board |
| --- | --- | --- |
| Server | bpi-m4-kernel | About 1.9 GiB |
| Media | bpi-m4-kernel-media | About 1.7 GiB; hardware confirmation required |

The Media DTB reserves memory for firmware, heaps and video output before Linux
allocation. Installing players alone cannot change this layout or start ACPU.
Native kernel/codecs builds passed, but complete Media distribution remains
blocked by unresolved vendor firmware rights. Media RPC/display and reset still
need hardware qualification. See [MEDIA-FIRMWARE.md](MEDIA-FIRMWARE.md).

With compatible firmware and required packages installed, the operator selects:

```sh
sudo bpi-m4-mode media
sudo poweroff
```

Disconnect power for at least five seconds and reconnect. Use the same procedure
with `sudo bpi-m4-mode server` to return. `bpi-m4-mode status` reports current and
next selections without privilege. Selection changes extlinux's persistent
default; it does not reboot, write SPI or repartition SD.

The loader must advertise bananapi,spi-media-handoff = "v1", validate reserved
memory and inactive ACPU/RPC, and arm Media's EL3 handoff while keeping ACPU off.
Linux verifies and loads firmware from SD. Mode selection requires verified
firmware/player packages. Earlier loaders need a separately qualified SPI update.

Installing another mode preserves selection. Updates advance only the selected
mode; older entries remain for fallback and removal preserves one Server kernel.
HDMI startup remains an explicit operator hardware test using
`sudo bpi-m4-hdmi-start`. Hardware video decoding and automatic failed-boot
rollback are not implemented. See [KERNEL-UPDATES.md](KERNEL-UPDATES.md).
