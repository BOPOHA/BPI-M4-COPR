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

COPR builds natively on fedora-45-aarch64 against six hash/signature-verified
Fedora sysroot RPMs. Their URLs, NEVRAs and trust anchor are pinned in the codec
lock. No vendor compiler or libc is used. The SPEC retains an optional cross
toggle; see [BUILD-PATHS.md](BUILD-PATHS.md).

```sh
make build PACKAGE=bpi-m4-native-codecs
```

The COPR source worker verifies inputs and prepares a self-contained SRPM.
The [SPEC](../packaging/bpi-m4-native-codecs.spec) extracts the sysroot, compiles
the private library and audits architecture, SONAME and dependencies. Its audit
JSON, source provenance and license accompany the RPM. Server images exclude
this optional package; image assembly is maintained in BPI-M4-IMAGE.

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
