# Preserve the selected default in the SRPM; --with/--without media can override it.
Source98: bpi-build-profile
%bcond media %["%(cat %{SOURCE98})" == "media"]
%if %{with media}
%global bpi_profile media
%global bpi_other_profile server
%else
%global bpi_profile server
%global bpi_other_profile media
%endif
# The SPI update variant is retained in its SRPM; legacy SD defaults stay separate.
Source96: bpi-boot-mode
%bcond boot_updates %["%(cat %{SOURCE96})" == "spi"]
%bcond cross %["%{_host_cpu}" != "aarch64"]
Source95: kernel-update-release
%global bpi_update_release %(cat %{SOURCE95})
# Cross builds must not run host architecture stripping or dependency scanners.
%global debug_package %{nil}
%global __os_install_post %{nil}
%global _build_id_links none
%global _buildshell /bin/bash
%if %{with boot_updates}
%if %{with media}
Name: bpi-m4-kernel-media
%else
Name: bpi-m4-kernel
%endif
%else
Name: bpi-m4-kernel-%{bpi_profile}
%endif
Version: 7.3.5
%if %{with media}
%global bpi_kernel_release %{version}-bpi-m4-fc-p14-media
%else
%global bpi_kernel_release %{version}-bpi-m4-fc-p10
%endif
Source99: bpi-build-id
%global bpi_recipe %(cat %{SOURCE99})
%if %{with boot_updates}
%if %{with media}
%global bpi_kernel_base bpi_m4_fc_p14_media
%else
%global bpi_kernel_base bpi_m4_fc_p10
%endif
%global bpi_kernel_release %{version}-%{bpi_kernel_base}.r%{bpi_update_release}.%{bpi_recipe}
Release: %{bpi_update_release}.%{bpi_recipe}.bpi_m4.fc45
%global bpi_artifact_dir /usr/lib/bpi-m4/kernels/%{bpi_kernel_release}
%global bpi_doc_dir /usr/share/doc/%{name}/%{bpi_kernel_release}
%global bpi_license_dir /usr/share/licenses/%{name}/%{bpi_kernel_release}
%global bpi_localversion LOCALVERSION=.r%{bpi_update_release}.%{bpi_recipe}
%else
Release: 1.%{bpi_recipe}.bpi_m4.fc45
%global bpi_artifact_dir /usr/lib/bpi-m4/kernel-%{bpi_profile}
%global bpi_doc_dir /usr/share/doc/%{name}
%global bpi_license_dir /usr/share/licenses/%{name}
%global bpi_localversion %{nil}
%endif
%if %{with cross}
%global bpi_cross CROSS_COMPILE=aarch64-linux-gnu-
%else
%global bpi_cross %{nil}
%endif
%global bpi_make_args ARCH=arm64 %{bpi_cross} %{bpi_localversion}
Summary: Matched Linux kernel, DTB and modules for BPI-M4 (%{bpi_profile})
License: GPL-2.0-only
URL: https://www.kernel.org/
Source0: linux-%{version}.tar.xz
Source1: bpi-m4-kernel-inputs.tar.gz
Source2: kernel.required.config
Patch10: 10-secondary-cpus.patch
Patch20: 20-sb2-barriers.patch
Patch30: 30-watchdog-restart.patch
Patch40: 40-board-integration.patch
Patch50: 0038-usb-dwc3-rtk-apply-the-RTD1395-quirk-by-compatible.patch
Patch51: 0039-phy-realtek-usb2-fix-the-PHY-register-of-the-second-.patch
Patch60: mmc-readonly-core.patch
Patch61: gpio-shared-iso.patch
Patch70: 50-emmc-clock-handoff.patch
%if %{with media}
Patch90: firmware-display.patch
%endif
%if %{with cross}
BuildRequires: gcc-aarch64-linux-gnu
BuildRequires: binutils-aarch64-linux-gnu
%else
BuildRequires: binutils
%endif
BuildRequires: gcc
BuildRequires: make
BuildRequires: bc
BuildRequires: bison
BuildRequires: flex
BuildRequires: elfutils-libelf-devel
BuildRequires: openssl-devel
BuildRequires: perl
BuildRequires: kmod
BuildRequires: patch
BuildRequires: xz
BuildRequires: jq
BuildRequires: dtc
AutoReqProv: no
Requires: kmod
Provides: bpi-m4-kernel-uname-r(%{bpi_kernel_release})
%if %{with boot_updates}
Provides: kernel-uname-r = %{bpi_kernel_release}
Provides: installonlypkg(kernel)
Provides: bpi-m4-kernel-mode(%{bpi_profile})
Requires: bpi-m4-sd-boot >= 2
Requires(posttrans): bpi-m4-sd-boot
Requires(preun): bpi-m4-sd-boot
Requires(post): coreutils
%else
Conflicts: bpi-m4-kernel-%{bpi_other_profile}
%endif

%description
Linux and its exact matching modules, with source-prepared RTD1395 board ports.
Boot artifacts are staged under /usr/lib/bpi-m4. The SPI update variant installs
an immutable versioned boot bundle and selects it through extlinux after the
transaction. Legacy SD variants stage payloads without activation. No variant
writes SPI, the FAT boot partition or eMMC, or reboots the device.

%if %{with boot_updates} && %{without cross}
%package devel
Summary: Prepared external-module build tree for %{bpi_kernel_release}
AutoReqProv: no
Requires: kernel-uname-r = %{bpi_kernel_release}
Provides: kernel-devel-uname-r = %{bpi_kernel_release}
Provides: installonlypkg(kernel)

%description devel
Matching prepared ARM64 kernel tree, configuration, symbols and native build
helpers for external modules. Install a native compiler and make separately.

%endif

%prep
%autosetup -N -n linux-%{version} -a 1 -p1
inputs=bpi-m4-kernel-inputs
port="$inputs/src/linux/peripherals"
# Authenticate the pristine imports before copying or applying media changes.
(
  cd "$port"
  jq -r 'to_entries[] | "\(.value)  \(.key)"' import-sha256.json | sha256sum --check --strict
)
for file in bpi-m4-sd-cmd18.c write-policy.h; do
  install -Dpm0644 "$inputs/src/linux/mmc/$file" "drivers/mmc/host/$file"
done
install -Dpm0644 "$inputs/src/linux/ethernet/rtd1395-ethernet.c" drivers/net/ethernet/realtek/bpi-m4-ethernet.c
cp -a "$port/drivers/." .
board=arch/arm64/boot/dts/realtek/bpi-m4-fc.dts
install -Dpm0644 "$inputs/src/linux/board.dts" "$board"
install -pm0644 "$inputs/config/kernel.config" .config
# Imported audio sources must exist before the conditional media patch applies.
%autopatch -p1
printf '\n' >>"$board"
cat "$port/board-fc.dtsi" >>"$board"
bash scripts/kconfig/merge_config.sh -m .config "$port/fc.config"
%if %{with media}
printf '\n' >>"$board"
cat "$inputs/src/linux/media/board-media.dtsi" >>"$board"
bash scripts/kconfig/merge_config.sh -m .config "$inputs/src/linux/media/media.config"
%else
printf '\n' >>"$board"
cat "$inputs/src/linux/board-server.dtsi" >>"$board"
%endif

%build
unset CFLAGS CXXFLAGS CPPFLAGS LDFLAGS
test '%{_target_cpu}' = aarch64
%if %{with boot_updates}
scripts/config --set-str LOCALVERSION '-%{bpi_kernel_base}'
%endif
make %{bpi_make_args} olddefconfig
while IFS= read -r option; do
  grep -Fxq -- "$option" .config || { echo "Unresolved required kernel option: $option" >&2; exit 1; }
done < "%{SOURCE2}"
%make_build %{bpi_make_args} Image realtek/bpi-m4-fc.dtb modules

%install
set -eo pipefail
mkdir -p "%{buildroot}/usr/lib"
ln -s usr/lib "%{buildroot}/lib"
make %{bpi_make_args} modules_install INSTALL_MOD_PATH="%{buildroot}" DEPMOD=true
modules="%{buildroot}/usr/lib/modules/%{bpi_kernel_release}"
rm -f "$modules/build" "$modules/source"
depmod -b "%{buildroot}" "%{bpi_kernel_release}"
rm "%{buildroot}/lib"
dest="%{buildroot}%{bpi_artifact_dir}"
mkdir -p "$dest"
install -pm644 arch/arm64/boot/Image "$dest/Image"
install -pm644 arch/arm64/boot/dts/realtek/bpi-m4-fc.dtb "$dest/board.dtb"
install -pm644 .config "$dest/kernel.config"
install -pm644 Module.symvers "$dest/Module.symvers"
%if %{with boot_updates}
printf '%%s\n' '%{bpi_profile}' >"$dest/boot-profile"
%endif
config_sha=$(sha256sum "$dest/kernel.config" | cut -d ' ' -f 1)
symvers_sha=$(sha256sum "$dest/Module.symvers" | cut -d ' ' -f 1)
find "$modules" -type f -name '*.ko' -exec sha256sum --zero {} + | \
  jq -Rs --arg prefix "$modules/" \
    'split("\u0000") | map(select(length > 0) | {key: (.[66:] | ltrimstr($prefix)), value: .[:64]}) | from_entries' > module-hashes.json
jq -nS --arg release "%{bpi_kernel_release}" --arg version "%{version}" \
  --arg config "$config_sha" --arg symvers "$symvers_sha" --slurpfile modules module-hashes.json \
  '{release:$release, source_version:$version, config_sha256:$config, module_symvers_sha256:$symvers, modules_sha256:$modules[0], hardware_validated:false}' > "$dest/kernel-manifest.json"
(cd "$dest"; sha256sum Image board.dtb kernel.config Module.symvers kernel-manifest.json >SHA256SUMS)
%if %{with boot_updates}
(cd "$dest"; sha256sum boot-profile >>SHA256SUMS)
%endif
install -Dpm644 COPYING "%{buildroot}%{bpi_license_dir}/COPYING"
install -Dpm644 bpi-m4-kernel-inputs/provenance.json "%{buildroot}%{bpi_doc_dir}/provenance.json"

%if %{with boot_updates} && %{without cross}
devel="%{buildroot}/usr/src/kernels/%{bpi_kernel_release}"
mkdir -p "$devel"
# Preserve all Kbuild/Makefiles and headers, including internal board-driver headers.
find . -type f \( -name Makefile -o -name 'Makefile.*' -o -name Kbuild -o -name 'Kbuild.*' -o -name '*.h' -o -name '*.lds' -o -name '*.lds.S' \) -print0 | tar --null -T - -cf - | tar -C "$devel" -xf -
cp -a include scripts "$devel/"
mkdir -p "$devel/arch/arm64"
cp -a arch/arm64/include "$devel/arch/arm64/"
mkdir -p "$devel/arch/arm64/tools"
cp -a arch/arm64/tools/. "$devel/arch/arm64/tools/"
cp -a .config Module.symvers "$devel/"
ln -s "/usr/src/kernels/%{bpi_kernel_release}" "$modules/build"
%endif

%check
set -eo pipefail
test "$(make -s %{bpi_make_args} kernelrelease)" = "%{bpi_kernel_release}"
grep -Fq rtl8169_soc_driver System.map
dest="%{buildroot}%{bpi_artifact_dir}"
modules="%{buildroot}/usr/lib/modules/%{bpi_kernel_release}"
mapfile -d '' built_modules < <(find "$modules" -type f -name '*.ko' -print0)
test "${#built_modules[@]}" -gt 0
for module in "${built_modules[@]}"; do
  vermagic=$(modinfo -F vermagic "$module")
  case "$vermagic" in
    "%{bpi_kernel_release} "*) ;;
    *) echo "Kernel module ABI mismatch: $module" >&2; exit 1;;
  esac
done
test "$(od -An -tx1 -j56 -N4 "$dest/Image" | tr -d '[:space:]')" = 41524d64
test "$(od -An -tx1 -N4 "$dest/board.dtb" | tr -d '[:space:]')" = d00dfeed
%if %{without media}
memory_status=disabled
%else
memory_status=okay
%endif
for node in audio@2600000 media@3200000 acpu@f900000; do
  test "$(fdtget -t s -d okay arch/arm64/boot/dts/realtek/bpi-m4-fc.dtb "/reserved-memory/$node" status)" = "$memory_status"
done
test "$(fdtget -t s arch/arm64/boot/dts/realtek/bpi-m4-fc.dtb /chosen bananapi,boot-profile)" = '%{bpi_profile}'

%if %{with boot_updates} && %{without cross}
smoke=$(mktemp -d)
printf 'obj-m := smoke.o\n' >"$smoke/Makefile"
printf '#include <linux/module.h>\nstatic int __init smoke_init(void) { return 0; }\nstatic void __exit smoke_exit(void) {}\nmodule_init(smoke_init); module_exit(smoke_exit);\nMODULE_LICENSE("GPL");\n' >"$smoke/smoke.c"
make -C "%{buildroot}/usr/src/kernels/%{bpi_kernel_release}" %{bpi_make_args} M="$smoke" modules
test "$(modinfo -F vermagic "$smoke/smoke.ko" | cut -d ' ' -f1)" = '%{bpi_kernel_release}'
test -f "%{buildroot}/usr/src/kernels/%{bpi_kernel_release}/drivers/mmc/core/card.h"
rm -rf "$smoke"
%endif

%files
/usr/lib/modules/%{bpi_kernel_release}
%if %{with boot_updates} && %{without cross}
%exclude /usr/lib/modules/%{bpi_kernel_release}/build
%endif
%{bpi_artifact_dir}
%doc %{bpi_doc_dir}
%license %{bpi_license_dir}

%if %{with boot_updates} && %{without cross}
%files devel
/usr/src/kernels/%{bpi_kernel_release}
/usr/lib/modules/%{bpi_kernel_release}/build
%endif

%if %{with boot_updates}
%post -p /bin/bash
# Keep an incoming ABI during reinstall; /run markers are transaction-local.
mkdir -p /run/bpi-m4-kernel-updates
printf '%%s\n' "$PPID" >/run/bpi-m4-kernel-updates/installing-%{bpi_kernel_release}

%posttrans -p /bin/bash
/usr/sbin/bpi-m4-bootctl add '%{bpi_kernel_release}'
status=$?
rm -f /run/bpi-m4-kernel-updates/installing-%{bpi_kernel_release}
exit "$status"

%preun -p /bin/bash
# Other installed kernel versions also contribute to RPM's $1 count. Preserve
# this ABI only when its incoming installation belongs to this RPM process.
marker=/run/bpi-m4-kernel-updates/installing-%{bpi_kernel_release}
if [[ $1 -gt 0 && -f $marker && $(cat "$marker") == "$PPID" ]]; then
    exit 0
fi
/usr/sbin/bpi-m4-bootctl remove '%{bpi_kernel_release}'
%endif
