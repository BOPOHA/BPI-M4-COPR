Destination: https://copr.fedorainfracloud.org/coprs/vorona/bpi-m4/
Chroot: fedora-45-aarch64. Git: https://github.com/BOPOHA/BPI-M4-COPR

Do not upload optional vendor firmware until redistribution rights are resolved.
Required Server packages: board-support, kernel (plus native devel), sd-boot.
Use successful native builds and the project's actual GPG key for IMAGE locks.
Native dependency parsing is not proof of successful native compilation.

copr-cli is installed rootlessly at /tmp/bpi-copr-bin/copr-cli for this session.
~/.config/copr needs the [copr-cli] API credentials from
https://copr.fedorainfracloud.org/api/. No new COPR builds submitted.

After credentials are configured:

```sh
/tmp/bpi-copr-bin/copr-cli build vorona/bpi-m4 out/srpms/board.src.rpm out/srpms/sd-boot.src.rpm out/srpms/kernel-updates.src.rpm
```
