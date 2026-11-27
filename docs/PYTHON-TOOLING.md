Python tooling review, 2026-11-27

The helper package is now bpi_packaging instead of the historical bpi_image.
Make entry points, imports, test mocks, SPEC invocations, source recipe hashes
and SRPM payload paths use the new name. Existing cached receipts include recipe
paths/hashes and are invalidated when recipes change. No compatibility package
is kept; use python3 -m bpi_packaging.rpm_packages for direct invocations.

Unused imports were removed from inputs.py and initramfs.py. In particular,
inputs.py no longer imports YAML; host instructions and the checks SPEC no longer
require PyYAML. The maintained helper package uses the Python standard library
and invokes declared external build tools. The source tree may still contain
upstream YAML bindings; that does not require PyYAML for our source preparation.

Python remains useful for deterministic SRPM archives, source/signature checks,
build receipts, target ELF dependency closure, safe target symlink resolution,
initramfs serialization, codec ABI audits and regression harnesses. No new
Python requirement is added to target kernel or boot payloads. Native ARM64 and
laptop cross build paths remain supported.

Validation: regular-user make checks passed in Mock: 15 Python regressions plus
the compiled eMMC clock guard. Local make test could not run because the host
has no C compiler; Mock supplied the declared compiler dependency. SD-boot and
codec SRPM preparation succeeded with the renamed helpers. Native ARM64 package
verification is recorded in VALIDATION.md. No host packages or devices were
modified.

SRPM orchestration cleanup

The redundant bpi_packaging/copr_source.py bridge was replaced with
scripts/copr-srpm.bash. Package routing is declared once in
packaging/copr-scm.json. The Bash entry point selects the profile, checks the
prepared SRPM's hash and package name, and copies it to COPR's output directory.
Unused image-era DNF configuration functions and the unused --request argument
were removed. The Python source preparer remains responsible for deterministic
archives, structured receipts, pinned source verification and binary audits.

The kernel update revision advances to 6 for the Bash source-entry verification
build, so the new recipe sorts after revision 5 regardless of its hash suffix.
Previously published kernel generations remain available as fallbacks.
