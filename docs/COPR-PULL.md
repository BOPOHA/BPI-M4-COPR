COPR Git pull builds

Default package sources use Git SCM and make_srpm, following the .copr/Makefile
pattern in BOPOHA/hamsterd and BOPOHA/transmission-navi. Plain rpkg preprocessing
(as in openlawsvpn/go-openlawsvpn) is insufficient here: our SRPM stage must
select a kernel profile, verify pinned upstream signatures and RPMs, and prepare
several generated source archives. make_srpm reuses that preparation and invokes
rpkg to create the final self-contained SRPM.

For each package in packaging/copr-scm.json, configure these COPR UI fields:

- Source Type: Build from an SCM repository
- SCM type: git
- Clone URL: https://github.com/BOPOHA/BPI-M4-COPR.git
- Committish: main (or an exact Git commit for a pinned rebuild)
- Path to .spec file: the package's spec value in packaging/copr-scm.json
- Build SRPM with: make_srpm

The Media selector packaging/bpi-m4-kernel-media.spec is a symlink to the shared
kernel SPEC. The source entry point selects Media from the configured filename;
the generated SRPM contains the same shared SPEC plus a Media profile source.
Server uses packaging/bpi-m4-kernel.spec. Both produce versioned update packages.

The network-enabled, isolated COPR source worker runs .copr/Makefile, installs
its source-preparation dependencies internally, and invokes scripts/copr-srpm.bash
with COPR's spec/outdir arguments. Do not use that Makefile for host setup.
Source preparation needs no Mock or compiler. Its identity fingerprints pinned
inputs and preparation recipes without querying local Mock versions/config.
The checked-in public Fedora 45 key is verified against its pinned fingerprint,
so a source worker running a different Fedora release can verify target RPMs.
Key fingerprint checks use temporary private GnuPG homes, independent of user
keyrings or source-worker home directories. Git ownership exceptions are scoped
to subprocesses. Architecture buildroots
receive the complete SRPM and compile natively on fedora-45-aarch64.

Reconcile package settings using an authenticated COPR CLI:

```sh
./scripts/configure-copr-scm.bash
copr-cli build-package --nowait -r fedora-45-aarch64 --name bpi-m4-board-support vorona/bpi-m4
```

The configuration helper edits existing upload sources and adds missing packages.
It does not upload SRPMs or start builds. Webhook rebuilding is off; request
build-package explicitly. Media firmware is excluded until redistribution rights
are resolved. Module checks retain the exact kernel-devel RPM/key/ABI pins in
inputs.module-check.lock.json; review that lock when selecting a new kernel.

COPR Git pull is the only supported build interface. Local SRPM/Mock targets,
product caches and the legacy unversioned kernel package mode have been removed.
The internal source-worker helpers still assemble self-contained SRPMs; no SRPM
upload step is required. GHA triggering is maintained separately by the operator.

A successful kernel release still requires reviewing the IMAGE input lock before
it is selected for an image. No Git pull build flashes or qualifies hardware.

See [VALIDATION.md](VALIDATION.md) and [validation.json](validation.json) for
the successful native builds and exact artifact pins.
