Name: bpi-m4-board-support
Version: 2
Source99: bpi-build-id
%global bpi_recipe %(cat %{SOURCE99})
Release: 2.%{bpi_recipe}.bpi_m4.fc45
Summary: Configuration and documentation for the original Banana Pi M4
License: GPL-2.0-or-later
Source0: bpi-m4-board-support.tar.gz
BuildArch: noarch
Requires: openssh-server
Requires: kmod

%description
Board configuration and first-boot instructions. User names, passwords, SSH
keys, host identities and root partition UUIDs are supplied by image provisioning.

%package -n bpi-m4-media-support
Summary: Explicit HDMI startup and diagnostics for BPI-M4
Requires: bpi-m4-board-support = %{version}-%{release}
Requires: bash
Requires: kmod

%description -n bpi-m4-media-support
Headless HDMI test commands and documentation. Firmware startup remains explicit.

%package -n bpi-m4-media
Summary: Optional Media mode for the common BPI-M4 Fedora image
Requires: bpi-m4-kernel-mode(media)
Requires: bpi-m4-sd-boot >= 2
Requires: bpi-m4-media-support = %{version}-%{release}
Requires: bpi-m4-media-firmware
Requires: bpi-m4-native-codecs
Requires: mpv
Requires: openh264
Requires: gstreamer1
Requires: gstreamer1-plugins-base
Requires: gstreamer1-plugins-bad-free
Requires: v4l-utils
Requires: libgpiod-utils
Requires: dosfstools
Requires: file
Requires: drm-utils

%description -n bpi-m4-media
Installs a versioned Media kernel, firmware, player and diagnostic packages.
Server stays selected until bpi-m4-mode media is run. A physical power cycle
is required after selecting a mode. Both modes share the same Fedora root.

%prep
%setup -q -n bpi-m4-board-support

%install
cp -a payload/. "%{buildroot}/"

%files
%config(noreplace) /etc/ssh/sshd_config.d/10-bpi-m4.conf
%config(noreplace) /etc/modprobe.d/bpi-m4-peripherals.conf
%doc /usr/share/doc/bpi-m4/first-boot.md
%doc /usr/share/doc/bpi-m4/provenance.json
%license /usr/share/licenses/bpi-m4-board-support/COPYING

%files -n bpi-m4-media-support
%config(noreplace) /etc/modprobe.d/bpi-m4-media.conf
/usr/bin/bpi-m4-hdmi-start
%doc /usr/share/doc/bpi-m4/media-firmware.md

%files -n bpi-m4-media
