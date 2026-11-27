%global debug_package %{nil}
%global __os_install_post %{nil}
%global _build_id_links none
Name: bpi-m4-native-codecs
Version: 9.0.2
Source99: bpi-build-id
%global bpi_recipe %(cat %{SOURCE99})
Release: 4.%{bpi_recipe}.bpi_m4.fc45
Summary: Private ARM native video decoders for BPI-M4 playback
License: LGPL-2.1-or-later AND GPL-2.0-or-later
URL: https://ffmpeg.org/
Source0: ffmpeg-%{version}.tar.xz
Source1: bpi-m4-codec-inputs.tar.gz
%bcond cross %["%{_host_cpu}" != "aarch64"]
%if %{with cross}
BuildRequires: gcc-aarch64-linux-gnu
BuildRequires: binutils-aarch64-linux-gnu
%else
BuildRequires: binutils
%endif
BuildRequires: gcc
BuildRequires: make
BuildRequires: python3
BuildRequires: rpm
BuildRequires: cpio
AutoReqProv: no
Requires: mpv
Requires: libavutil.so.61()(64bit)
Requires: libc.so.6()(64bit)
Requires: libm.so.6()(64bit)
Requires: glibc >= 2.44

%description
Source-built LGPL decoders for explicit bpi-m4-play invocation. The private
library does not replace or provide the system libavcodec RPM capability.
The cross sysroot is assembled from pinned Fedora-signed development packages.

%prep
%setup -q -n ffmpeg-%{version} -a 1
PYTHONPATH=bpi-m4-codec-inputs python3 -c 'from pathlib import Path; from bpi_packaging.media_codecs import prepare_sysroot; prepare_sysroot(Path("bpi-m4-codec-inputs").resolve())'

%build
# Fedora's rpmbuild exports host compiler specs; use the audited cross recipe.
unset CFLAGS CXXFLAGS CPPFLAGS LDFLAGS
mkdir -p bpi-build
cd bpi-build
sysroot="$PWD/../bpi-m4-codec-inputs/sysroot"
%if %{with cross}
compiler=(--enable-cross-compile --cc=aarch64-linux-gnu-gcc --ar=aarch64-linux-gnu-ar --nm=aarch64-linux-gnu-nm --ranlib=aarch64-linux-gnu-ranlib --strip=aarch64-linux-gnu-strip)
strip_tool=aarch64-linux-gnu-strip
%else
compiler=(--cc=gcc --ar=ar --nm=nm --ranlib=ranlib --strip=strip)
strip_tool=strip
%endif
../configure "${compiler[@]}" --arch=aarch64 --cpu=cortex-a53 --target-os=linux \
  --sysroot="$sysroot" \
  --extra-cflags=-mcpu=cortex-a53 \
  --extra-ldflags="-L$sysroot/usr/lib64 -fno-link-libatomic -Wl,--fix-cortex-a53-843419,-z,defs" \
  --prefix=/usr --libdir=/usr/lib64/bpi-m4-codecs --disable-autodetect \
  --disable-doc --disable-programs --disable-static --enable-shared \
  --disable-avformat --disable-avdevice --disable-avfilter --disable-swresample \
  --disable-swscale --disable-network --disable-encoders
%make_build CONFIG_ELBG_FILTER=yes libavcodec/libavcodec.so.63
$strip_tool --strip-unneeded libavcodec/libavcodec.so.63

%install
install -Dpm755 bpi-build/libavcodec/libavcodec.so.63 "%{buildroot}/usr/lib64/bpi-m4-codecs/libavcodec.so.63"
install -Dpm755 bpi-m4-codec-inputs/bpi-m4-play "%{buildroot}/usr/bin/bpi-m4-play"
install -Dpm644 bpi-m4-codec-inputs/provenance.json "%{buildroot}/usr/share/doc/%{name}/provenance.json"
install -Dpm644 bpi-m4-codec-inputs/MEDIA-CODECS.md "%{buildroot}/usr/share/doc/%{name}/MEDIA-CODECS.md"
install -Dpm644 COPYING.LGPLv2.1 "%{buildroot}/usr/share/licenses/%{name}/COPYING.LGPLv2.1"

%check
for flag in 'CONFIG_GPL 0' 'CONFIG_NONFREE 0' 'HAVE_NEON 1' 'CONFIG_H264_DECODER 1' 'CONFIG_HEVC_DECODER 1' 'HAVE_THREADS 1'; do
  grep -Fx "#define $flag" bpi-build/config.h bpi-build/config_components.h
done
PYTHONPATH=bpi-m4-codec-inputs python3 - "%{buildroot}" <<'PYCODE'
import sys
from pathlib import Path
from bpi_packaging.common import sha, write_json
from bpi_packaging.media_codecs import audit_abi
root = Path(sys.argv[1])
library = root/'usr/lib64/bpi-m4-codecs/libavcodec.so.63'
write_json(root/'usr/share/doc/bpi-m4-native-codecs/abi-audit.json',
           {'library_sha256':sha(library), 'abi_audit':audit_abi(library, None)})
PYCODE

%files
/usr/lib64/bpi-m4-codecs
/usr/bin/bpi-m4-play
%doc /usr/share/doc/%{name}
%license /usr/share/licenses/%{name}
