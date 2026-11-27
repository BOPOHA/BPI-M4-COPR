# First boot and SD expansion

Keep SW2=0, connect UART at 115200 8N1 and physically power on with the flashed
card. By default, UART (`ttyS0`) automatically opens a root shell without a
password. Anyone with UART access has full control of the board. Root's password
remains locked and root SSH login is disabled. Set `uart_root_autologin: false`
in the build YAML to disable this automatic console login.

Find its DHCP address and SSH as the configured user (default `fedora`) with
your public key. SSH requires public-key authentication for every user; password,
keyboard-interactive and empty-password authentication are disabled. Server
starts with a 1 GiB root; media starts with 2 GiB.

## Add an SSH key on the SD card

The configured user's `~/.ssh/authorized_keys` exists even when no key was
supplied during the build. It contains this inert example:

```text
# ssh-rsa changeme feroda@localhost
```

Replace that comment with one complete, real public key line, such as the
contents of `~/.ssh/id_ed25519.pub` on your computer. Do not copy a private key.
The placeholder becomes usable only after replacement with a valid public key.

Power off the board, move the SD to a Linux PC, identify the correct device and
unmount any desktop automounts. Run these commands manually with the actual
root partition name (p2); use your configured username if it differs:

```sh
sudo mkdir -p /mnt/bpi-root
sudo mount /dev/REPLACE_WITH_SD2 /mnt/bpi-root
sudoedit /mnt/bpi-root/home/fedora/.ssh/authorized_keys
sudo umount /mnt/bpi-root
sync
```

`sudoedit` preserves the file's ownership and mode. The `.ssh` directory is
mode `0700`, `authorized_keys` is `0600`, and both belong to the configured user.
Return the card to the board and boot, then connect with
`ssh fedora@ADDRESS`. Editing `authorized_keys` requires no RPM or image rebuild.

## Optional local user password

```sh
sudo passwd fedora
```

This sets a local console password for `fedora`; it does not change root UART
autologin or allow SSH password login. Replace the username if configured
differently. The configured account retains passwordless sudo.

## Expand root to the remaining card capacity

Expand before large DNF transactions on the small root. Board SD writes are
limited to root p2, so partition-table resizing is performed on a Linux PC.

1. Run `sync`, power the board off and move the SD to the PC.
2. Identify it with `lsblk -o NAME,SIZE,MODEL,SERIAL,MOUNTPOINTS` and unmount both
   partitions, including desktop automounts.
3. With `growpart` (Fedora `cloud-utils-growpart`) and `e2fsprogs` installed:

   ```sh
   sudo growpart /dev/REPLACE_WITH_SD 2
   sudo e2fsck -f /dev/REPLACE_WITH_SD2
   sudo resize2fs /dev/REPLACE_WITH_SD2
   sync
   ```

   Continue after e2fsck exit 0 or 1; resolve other errors first. Keep p2 start,
   UUID and p1 unchanged, add no partitions, and recheck for automounts before
   filesystem operations.
4. Return the card to the powered-off board and verify after boot:

   ```sh
   findmnt /
   df -h /
   cat /sys/devices/platform/bpi-m4-sd-cmd18/read_stats
   ```

The loader accepts p2 growth while validating its start, UUID, minimum size and
detected capacity. Reserved sectors/ext4 metadata mean free space will be less
than 100% of the card. No automatic resizing runs on the board.

## Updates

```sh
sudo dnf update
```

DNF updates Fedora userspace. Kernel/DTB/initramfs/loader changes require matched
project builds and modules. Boot FAT remains unmounted. eMMC is read-only;
Media users start HDMI explicitly with `sudo bpi-m4-hdmi-start`; server includes
no vendor media firmware. See [firmware dependencies](MEDIA-FIRMWARE.md).
