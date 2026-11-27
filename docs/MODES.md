# One image, Server and Media boot modes

`make image JOBS=8` builds one Fedora SD image, `out/fedora-bpi-m4.raw`, and
the optional Media RPMs. Server is the default. Both modes use the same ext4
root, accounts, network configuration and application data. The initial root
is 2 GiB; expand it to the available SD capacity before routine DNF updates.

| Mode | Kernel/device tree | RAM on the 2 GiB board | Packages |
| --- | --- | --- | --- |
| Server | `bpi-m4-kernel`; media processor disabled | About 1.9 GiB usable | Fedora server/network/storage packages |
| Media | `bpi-m4-kernel-media`; media memory reserved | About 1.7 GiB usable, requiring hardware confirmation | Server plus media firmware, drivers, players and diagnostics |

The Media kernel reserves 216 MiB for audio/media firmware and heaps, plus a
32 MiB video-output pool. These reservations take effect through its device
tree before Linux allocates RAM. Installing player packages alone does not
change memory or start the independent media processor.

## Install and select

Once the package repository is available:

```sh
sudo dnf install bpi-m4-media
sudo bpi-m4-mode media
sudo poweroff
```

Disconnect board power for at least five seconds, then reconnect it. To return:

```sh
sudo bpi-m4-mode server
sudo poweroff
```

Again disconnect and reconnect power. `bpi-m4-mode` changes the persistent
extlinux default; it does not reboot, write SPI or repartition the SD card.
Unprivileged `bpi-m4-mode status` reports the running and next boot selections.

The metapackage requires the SPI-compatible Media kernel, media support,
verified vendor firmware, native codecs, mpv and diagnostic packages. Installing
or updating another mode keeps the current selection. Updates of the selected
mode advance to its newest complete bundle. Older entries remain in the boot
menu for manual fallback; removal preserves at least one Server kernel.

For local testing before repository publication, copy these built RPMs to the
board and install them together through DNF:

```sh
sudo dnf install ./bpi-m4-media.rpm ./bpi-m4-kernel-media-updates.rpm \
    ./bpi-m4-media-support.rpm ./bpi-m4-media-firmware.rpm \
    ./bpi-m4-native-codecs.rpm
```

These aliases are under `out/rpms/`. A freshly built common image already has
the matching board-support and generic boot packages; older installations must
update those first. DNF supplies the Fedora dependencies. Public distribution
of the vendor firmware remains subject to the existing
[firmware redistribution review](MEDIA-FIRMWARE.md).

## Boot contract

One SPI U-Boot loads the selected versioned kernel, device tree and generic
initramfs from SD. It checks the memory layout against the selected profile,
requires inactive ACPU/RPC, and performs Media's EL3 secure handoff while keeping
the ACPU clock off. Linux loads the verified firmware and initializes its
drivers. The firmware stays on SD and is updated through its package.

The shared initramfs checks SD identity, writable-root bounds and matching
kernel modules for either mode. Media bundles cannot be selected by the OS
command unless its firmware/player packages are present and verified and the
running loader advertises Media handoff support. An earlier SPI loader needs
a separately reviewed firmware update before Media selection.

HDMI startup remains an explicit hardware test:

```sh
sudo bpi-m4-hdmi-start
```

Media RPC, display output and Media-to-Server reset are not yet hardware
qualified. Physical power cycling is the supported switching procedure.
Hardware video decoding is not implemented. There is no automatic failed-boot
rollback; Server remains available for manual recovery.

## Build products

`make image` builds the SPI candidate, both kernel variants, the generic boot
package, board/media support, firmware and codecs, and installs only the Server
packages into the common image. Component products are reused when unchanged.
`make media-rpms` builds just the optional packages. No build target flashes a
physical device. `make flash DEVICE=/dev/SD` is the manual flash-and-readback
target; the older flash-server/media names are aliases for this same image.

The original SD second-stage workflows remain available for historical
research as `make legacy-server-image` and `make legacy-media-image`; they are
separate from the common image and the new mode selector.
