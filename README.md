# BPI-M4-COPR

OS RPM sources and self-contained SRPM preparation; local Mock builds and native aarch64 COPR releases.

Host: Fedora 45; operator installs dependencies `mock mock-core-configs rpkg rpm-build python3-pyyaml gnupg2 git jq` manually. Mock runs
only through `/usr/bin/mock` as the regular user. No sudo/authentication is
started by build scripts. No sibling checkout or submodule is required.

Run `make help` for build/test targets. `make clean` removes this project's
products; `make clean-hard` deletes all ignored content, including cache/work/out.
Preserve useful artifacts outside the checkout first.

See [boot contract](docs/BOOT-CONTRACT.md), [extraction](docs/EXTRACTION.md),
[approved plan](docs/REPOSITORY-SPLIT.md) and [provenance](docs/PROVENANCE.md).
Native Server/Media kernel-devel, boot, support and codec COPR builds passed.
See docs/VALIDATION.md. Vendor firmware publication and new hardware
qualification remain pending.

Licensing: extracted code retains GPL/LGPL and imported notices. Selected new
standalone files use [As-Is Noncommercial terms](licenses/As-Is-Noncommercial.txt).
See [license scope](LICENSE.md).

Both [native ARM64 and laptop cross builds](docs/BUILD-PATHS.md) are supported.
