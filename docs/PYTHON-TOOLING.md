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
