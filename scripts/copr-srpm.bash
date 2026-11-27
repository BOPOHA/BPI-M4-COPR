#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
# COPR make_srpm entry point; prepare one pinned, self-contained source package.
set -Eeuo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$repo"
spec= outdir= describe=0
while (( $# )); do
    case $1 in
        --spec) spec=${2:?}; shift 2;;
        --outdir) outdir=${2:?}; shift 2;;
        --describe) describe=1; shift;;
        *) echo "Unknown option: $1" >&2; exit 2;;
    esac
done
die() { echo "$*" >&2; exit 1; }
[[ -n $spec && -f $spec ]] || die 'A checked-in packaging/ SPEC is required.'
[[ $(realpath -- "$(dirname -- "$spec")") == "$repo/packaging" ]] || die 'SPEC must be a packaging/ entry.'
# Check the target but preserve the selector basename (Media is a SPEC symlink).
[[ $(dirname -- "$(realpath -- "$spec")") == "$repo/packaging" ]] || die 'SPEC target is outside packaging/.'
entry=$(jq -ce --arg spec "packaging/${spec##*/}" \
    '[.packages[] | select(.spec==$spec)] | if length==1 then .[0] else error("Unsupported source package") end' packaging/copr-scm.json)
if (( describe )); then printf '%s\n' "$entry"; exit 0; fi
[[ -n $outdir ]] || die '--outdir is required.'
outdir=$(realpath -m -- "$outdir")
mkdir -p -- "$outdir"
component=$(jq -er .component <<<"$entry")
profile=$(jq -er .profile <<<"$entry")
alias=$(jq -er .alias <<<"$entry")
export BPI_COPR_SOURCE=1 PYTHONDONTWRITEBYTECODE=1 PATH="$repo/scripts/rpm-tools:$PATH"
# Scope Git's ownership exception to subprocesses, never host Git configuration.
count=${GIT_CONFIG_COUNT:-0}
[[ $count =~ ^[0-9]+$ ]] || die 'Invalid Git configuration count.'
export "GIT_CONFIG_KEY_$count=safe.directory" "GIT_CONFIG_VALUE_$count=$repo"
export GIT_CONFIG_COUNT=$((count+1))
if [[ $component == module-checks ]]; then
    ./scripts/prepare-module-check.bash
    source=$(realpath out/srpms/module-checks.src.rpm)
else
    python3 -m bpi_packaging.rpm_packages "$component" --profile "$profile" --srpm
    record="out/srpms/$alias.json"
    jq -e '.srpms | length==1' "$record" >/dev/null || die 'Exactly one SRPM required.'
    source=$(jq -er '.srpms[0].path' "$record")
    digest=$(jq -er '.srpms[0].sha256' "$record")
    printf '%s  %s\n' "$digest" "$source" | sha256sum --check --status
fi
[[ $(rpm -qp --qf '%{NAME}' "$source") == "$(jq -r .name <<<"$entry")" ]] || die 'Prepared SRPM package name differs from configuration.'
target="$outdir/${source##*/}"
[[ $(realpath -- "$source") == "$target" ]] || cp -- "$source" "$target"
printf 'COPR source package: %s\n' "$target"
