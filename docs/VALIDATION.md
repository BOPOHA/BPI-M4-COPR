# Native build validation

All seven COPR Git pull builds passed on fedora-45-aarch64:

| Package | COPR build |
| --- | --- |
| Regression checks | 11401218 |
| SD boot | 11401220 |
| Server kernel/devel | 11400871 |
| Media kernel/devel | 11400872 |
| Native codecs | 11401221 |
| Board support | 11401219 |
| Exact r7 devel external-module check | 11400987 |

The suite passed 20 Python regressions and the compiled eMMC clock guard.
Both kernels passed ABI, DTB and native module smoke checks. The signed Server
devel pin was verified and the external-module check passed with matching
vermagic and the internal MMC header, without ARCH/CROSS/LOCALVERSION overrides.
See [validation.json](validation.json) for exact public API states and pins.

Only COPR Git pull is supported. Local upload/Mock builders and unversioned
kernel builds are retired. Firmware publication and new hardware qualification
remain unresolved. No laptop kernel build or hardware write was performed.
[Historical kernel lifecycle evidence](https://github.com/BOPOHA/BPI-M4-fc/blob/ab5375ceb78cdb83a8fc3d87257f866a81a5d35d/docs/hardware/spi-cpu-flash-2026-11-26.md)
and [eMMC clock investigation](https://github.com/BOPOHA/BPI-M4-fc/blob/ab5375ceb78cdb83a8fc3d87257f866a81a5d35d/docs/hardware/emmc-clock-2026-11-27.md)
remain in the frozen fc repository.
