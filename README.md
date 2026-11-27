# BPI-M4-COPR

OS RPM sources for native ARM64 COPR Git pull builds and repository hosting.
No sibling checkout or submodule is required.

Use `make configure` to reconcile COPR sources, `make build PACKAGE=bpi-m4-kernel`
to request a native build, and `make checks` to run the regression package on
COPR. These commands require an authenticated COPR CLI and jq. `make test` runs
local regressions when their compiler and RPM tooling are already installed.
No script starts sudo or authentication prompts.

See [boot contract](docs/BOOT-CONTRACT.md), [extraction](docs/EXTRACTION.md),
[approved plan](docs/REPOSITORY-SPLIT.md) and [provenance](docs/PROVENANCE.md).
Native Server/Media kernel-devel, boot, support and codec COPR builds passed.
See docs/VALIDATION.md. Vendor firmware publication and new hardware
qualification remain pending.

Licensing: extracted code retains GPL/LGPL and imported notices. Selected new
standalone files use [As-Is Noncommercial terms](licenses/As-Is-Noncommercial.txt).
See [license scope](LICENSE.md).

[COPR build workflow and SPEC toggles](docs/BUILD-PATHS.md).

See [Python tooling review](docs/PYTHON-TOOLING.md) for retained build/test roles
and removed dependencies.

[COPR Git pull builds](docs/COPR-PULL.md) use the checked-in `.copr/Makefile`
with source method `make_srpm`; COPR prepares SRPMs from this repository itself.
