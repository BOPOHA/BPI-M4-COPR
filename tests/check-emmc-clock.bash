#!/usr/bin/bash
# Exercise the patched driver's clock guard without touching hardware.
set -euo pipefail
project=$(cd -- "$(dirname -- "$0")/.." && pwd)
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
mkdir -p "$scratch/drivers/mmc/host"
cp "$project/src/linux/peripherals/drivers/drivers/mmc/host/emmc-rtd129x.c" \
    "$scratch/drivers/mmc/host/"
patch --silent -d "$scratch" -p1 < "$project/patches/linux/50-emmc-clock-handoff.patch"
driver="$scratch/drivers/mmc/host/emmc-rtd129x.c"
awk '/^#define[[:space:]]+(CRT_PLL_EMMC[134]|PLL_RSTB|EM_PLL_(80|100|200)MHZ|EM_CKGEN_CTL)[[:space:]]/ {print}' \
    "$driver" > "$scratch/emmc-clock-function.h"
awk '/^static int em_inherited_clock\(/ {active=1} active {print} active && /^}/ {exit}' \
    "$driver" >> "$scratch/emmc-clock-function.h"
${CC:-gcc} -std=c11 -Wall -Wextra -Werror -I "$scratch" \
    "$project/tests/emmc-clock-harness.c" -o "$scratch/check-emmc-clock"
"$scratch/check-emmc-clock"
