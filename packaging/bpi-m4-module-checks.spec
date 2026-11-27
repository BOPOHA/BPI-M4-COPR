%global debug_package %{nil}
%global __os_install_post %{nil}
%global _buildshell /bin/bash
Name: bpi-m4-module-checks
Version: 1
Source99: bpi-build-id
%global bpi_recipe %(cat %{SOURCE99})
Release: 1.%{bpi_recipe}.fc45
Summary: Native external-module test against a published BPI-M4 development RPM
License: GPL-2.0-or-later
Source0: kernel-devel.rpm
Source1: kernel-devel.sha256
Source2: kernel-release
BuildRequires: gcc
BuildRequires: make
BuildRequires: binutils
BuildRequires: kmod
BuildRequires: rpm
BuildRequires: cpio
BuildRequires: coreutils

%description
Build-only regression artifact. Tests the operator's external-module workflow
using an extracted published native development RPM, without rebuilding Linux.

%prep
mkdir -p tree module
(cd %{_sourcedir}; sha256sum --check --strict kernel-devel.sha256)
rpm2cpio %{SOURCE0} | (cd tree; cpio --quiet -idm --no-absolute-filenames)

%build
set -euo pipefail
test "$(uname -m)" = aarch64
release=$(cat %{SOURCE2})
tree="$PWD/tree/usr/src/kernels/$release"
printf 'obj-m := smoke.o\nccflags-y += -I%s/drivers/mmc/core\n' "$tree" >module/Makefile
cat >module/smoke.c <<'C'
#include <linux/module.h>
#include <linux/mmc/card.h>
#include <linux/mmc/host.h>
#include "card.h"
static int __init smoke_init(void) { return 0; }
static void __exit smoke_exit(void) {}
module_init(smoke_init); module_exit(smoke_exit);
MODULE_LICENSE("GPL");
C
# Exact operator command: no ARCH/CROSS_COMPILE/LOCALVERSION override.
make -C "$tree" M="$PWD/module" modules
test "$(modinfo -F vermagic module/smoke.ko | cut -d ' ' -f1)" = "$release"
printf 'Published native tree built smoke.ko with matching vermagic: %%s\n' "$release" >result.txt

%install
install -Dpm0644 result.txt %{buildroot}/usr/share/doc/%{name}/result.txt

%files
%doc /usr/share/doc/%{name}/result.txt
