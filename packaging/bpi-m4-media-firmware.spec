Name: bpi-m4-media-firmware
Version: 20190225
Source99: bpi-build-id
%global bpi_recipe %(cat %{SOURCE99})
Release: 2.%{bpi_recipe}.bpi_m4.fc45
Summary: Local test copy of pinned RTD1395 media firmware
License: LicenseRef-Redistribution-Not-Established
%global firmware_revision 25f5b88ec4ba34029f964693dc34028b26e6c67c
%global firmware_sha256 774832da0a18c1ba837ff41926502fb8444e83397562c7170c71435416aff4df
%global firmware_bytes 4319769
# Retain the download policy when RPM's standard URL helper fetches Source0.
%global __urlhelper_localopts --proto =https --proto-redir =https --connect-timeout 20 --max-time 300 --retry 3
%global firmware_url https://raw.githubusercontent.com/BPI-SINOVOIP/BPI-M4-bsp/%{firmware_revision}/rtk-pack/rtk/bpi-m4/configs/default/linux/bluecore.audio
Source0: %{firmware_url}
Source1: provenance.json
Source2: MEDIA-FIRMWARE.md
BuildRequires: jq
BuildRequires: coreutils
BuildArch: noarch
AutoReqProv: no

%description
Vendor firmware downloaded separately for the authorized local media build.
Redistribution rights have not been established. Keep this package and its
source RPM local until that review is complete. Firmware startup is explicit.

%prep
# Validate source bytes and provenance even when rebuilding this SRPM directly.
printf '%%s  %%s\n' '%{firmware_sha256}' '%{SOURCE0}' | sha256sum --check --strict
test "$(stat -c %%s '%{SOURCE0}')" -eq '%{firmware_bytes}'
test '%{firmware_bytes}' -gt 0
test '%{firmware_bytes}' -le "$((0x500000))"
jq -e --arg url '%{firmware_url}' --arg digest '%{firmware_sha256}' \
  --arg revision '%{firmware_revision}' --argjson bytes '%{firmware_bytes}' \
  '.schema == 1 and .filename == "bluecore.audio" and .url == $url and
   .sha256 == $digest and .bytes == $bytes and .source_revision == $revision' '%{SOURCE1}'

%install
install -Dpm644 "%{SOURCE0}" "%{buildroot}/usr/lib/firmware/realtek/rtd1395/bluecore.audio"
printf '%%s  bluecore.audio\n' '%{firmware_sha256}' >"%{buildroot}/usr/lib/firmware/realtek/rtd1395/SHA256SUMS"
install -Dpm644 "%{SOURCE1}" "%{buildroot}/usr/share/doc/%{name}/provenance.json"
install -Dpm644 "%{SOURCE2}" "%{buildroot}/usr/share/doc/%{name}/MEDIA-FIRMWARE.md"

%files
/usr/lib/firmware/realtek/rtd1395/bluecore.audio
/usr/lib/firmware/realtek/rtd1395/SHA256SUMS
%doc /usr/share/doc/%{name}
