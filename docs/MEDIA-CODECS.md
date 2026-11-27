Current workflow: COPR Git pull is the only supported build interface.
Local SRPM uploads and Mock targets below describe historical work and are
retired. Use [BUILD-PATHS.md](BUILD-PATHS.md) for current build commands; image
and SPI builds belong to the independent BPI-M4-IMAGE and BPI-M4-SPI repositories.

# Native software video decoding

The media image builds `bpi-m4-native-codecs`: a private native FFmpeg decoder
library and `bpi-m4-play`. It improves H.264 software decoding on Cortex-A53 and
uses the firmware-backed DRM output. RTD1395 hardware video decoding is not implemented.
Colour conversion, scaling and opaque scanout copies still consume CPU time.

## Use

```sh
sudo bpi-m4-hdmi-start
sudo openvt -c 7 -s -w -- bpi-m4-play /path/to/video.mp4
```

Use an unused VT and stop any existing player first. The helper selects the
platform DRM card, four software decoder threads, and disables audio/OSD.
Additional mpv options can override defaults. For lower-resolution video,
native-size output avoids enlargement; `--zimg-scaler=bilinear` offers cheaper
full-screen scaling. H.264 and HEVC decoders are compiled.

## Source and build inputs

All inputs are pinned in [inputs.media-codecs.lock.json](../inputs.media-codecs.lock.json).
Source: https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz, with detached `.asc`
signature. The upstream public key is https://ffmpeg.org/ffmpeg-devel.asc;
its primary fingerprint is `FCF986EA15E6E293A5644F10B4322F04D67658D8`, published
on https://ffmpeg.org/download.html. The builder verifies that identity and
signature in isolated GPG state, plus exact hashes. Downloads stay in ignored
cache; Git contains no codec binaries.

Fedora's `aarch64-linux-gnu-gcc` builds against six individually hash/signature
verified Fedora 45 aarch64 sysroot RPMs. URLs, NEVRAs and the Fedora trust
fingerprint are in the codec lock. No vendor compiler or libc is used.
Mock installs the compiler and build dependencies inside its Fedora 45 buildroot;
see [image prerequisites](BUILD.md).

```sh
make rpm-codecs JOBS=8
make img-media OUTPUT=out/media-new.raw WORK_DIR=work/media-new
```

The standalone target creates an RPM and SRPM without host root; media builds
include it automatically, and server omits it. The checked-in
[spec](../packaging/bpi-m4-native-codecs.spec) performs compilation and packaging;
host Python verifies downloads and collects source inputs. RPM `%prep` extracts
the signed sysroot RPMs inside Mock, `%build` compiles the private library, and
`%check` audits its architecture/SONAME and dependencies. The audit JSON is
packaged with the library and checked against its hash before publishing. Image
installation checks pinned runtime versions and runs `mpv --version` with the
private codec library and immediate symbol binding inside the libguestfs appliance.
Make tracks
recipe changes and reuses finished products. Stable aliases are
`out/rpms/bpi-m4-native-codecs.rpm` and `out/srpms/codecs.src.rpm`.

The configure recipe enables shared native decoders, Cortex-A53 NEON and
threads, and disables encoders, external autodetection, programs and networking.
`CONFIG_ELBG_FILTER=yes` at make time includes upstream `elbg.o` for private ELBG
symbols used by Fedora's existing libavfilter. `-fno-link-libatomic` avoids an
unavailable implicit cross library; `-z defs` still checks link dependencies.
The Cortex-A53 843419 linker workaround is enabled. LGPL-2.1-or-later license,
source identity and build provenance are installed by the RPM.

## RPM ownership and updates

The local RPM owns only `/usr/lib64/bpi-m4-codecs/libavcodec.so.63`,
`/usr/bin/bpi-m4-play`, documentation/provenance and licenses. It advertises no
system libavcodec provider and replaces no Fedora files. Only the helper sets
the private library path; other libraries, filters and mpv remain Fedora RPMs.

Build checks cover ARM64 architecture/SONAME, dependencies and every versioned
libavcodec/libavutil symbol used by locked Fedora consumers. Runtime changes
outside the reviewed lock are refused. The package requires libavutil ABI 61;
a Fedora update changing that ABI requires a matching component rebuild.

The locally built unsigned RPM has its verified upstream provenance and payload
hash recorded separately. Image installation uses target ARM RPM
`--nosignature` for declared hash-checked project packages, retaining dependency checks
and normal DNF signature policy for Fedora updates.

```sh
rpm -qf /usr/bin/bpi-m4-play /usr/lib64/bpi-m4-codecs/libavcodec.so.63
rpm -V bpi-m4-native-codecs
cat /usr/share/doc/bpi-m4-native-codecs/provenance.json
```
