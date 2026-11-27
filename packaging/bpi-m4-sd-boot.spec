%global debug_package %{nil}
%global __os_install_post %{nil}
%global _build_id_links none
%global _buildshell /bin/bash
Name: bpi-m4-sd-boot
Version: 2
Source99: bpi-build-id
%global bpi_recipe %(cat %{SOURCE99})
Release: 1.%{bpi_recipe}.bpi_m4.fc45
Summary: Generic SD initramfs and atomic extlinux kernel activation for BPI-M4
License: GPL-2.0-or-later
Source0: bpi-m4-sd-boot-inputs.tar.gz
BuildRequires: python3
BuildRequires: rpm
BuildRequires: cpio
%bcond cross %["%{_host_cpu}" != "aarch64"]
%if %{with cross}
BuildRequires: qemu-user-static-aarch64
BuildRequires: binutils-aarch64-linux-gnu
%else
BuildRequires: binutils
BuildRequires: coreutils
%endif
BuildRequires: bash
BuildRequires: gzip
Requires: bash
Requires: coreutils
Requires: findutils
Requires: grep
Requires: sed
Requires: gzip
Requires: util-linux-core
AutoReqProv: no

%description
A kernel-independent initramfs discovers the root by PARTUUID and verifies the
board SD driver's detected CID, capacity and root write bounds before mounting.
The kernel RPM calls bpi-m4-bootctl to verify and install immutable versioned
boot bundles, then atomically update extlinux. Older bundles remain available
for manual fallback. This package does not flash firmware or reboot the board.

%prep
%setup -q -n bpi-m4-sd-boot-inputs

%build
python3 -m bpi_packaging.sd_boot .

%install
dest="%{buildroot}/usr/lib/bpi-m4/sd-boot"
mkdir -p "$dest"
install -pm0644 artifacts/{initramfs.img,initramfs-manifest.json,SHA256SUMS} "$dest/"
install -Dpm0755 scripts/bpi-m4-bootctl "%{buildroot}/usr/sbin/bpi-m4-bootctl"
install -Dpm0755 scripts/bpi-m4-mode "%{buildroot}/usr/sbin/bpi-m4-mode"
install -Dpm0644 licenses/GPL-2.0.txt "%{buildroot}/usr/share/licenses/%{name}/COPYING"
install -Dpm0644 docs/KERNEL-UPDATES.md "%{buildroot}/usr/share/doc/%{name}/KERNEL-UPDATES.md"
install -Dpm0644 docs/MODES.md "%{buildroot}/usr/share/doc/%{name}/MODES.md"

%check
bash -n scripts/bpi-m4-bootctl
bash -n scripts/bpi-m4-mode
bash -n src/initramfs/init-sd
bash -n src/initramfs/sd-root.bash
(cd artifacts; sha256sum --check --strict SHA256SUMS)
gzip -t artifacts/initramfs.img

%files
/usr/lib/bpi-m4/sd-boot
/usr/sbin/bpi-m4-bootctl
/usr/sbin/bpi-m4-mode
%doc /usr/share/doc/%{name}
%license /usr/share/licenses/%{name}
