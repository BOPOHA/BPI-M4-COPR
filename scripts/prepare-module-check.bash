#!/usr/bin/bash
set -Eeuo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$repo"
work="$repo/work/rpms/module-checks"
./scripts/clean-rpm-work.bash "$work"
mkdir -p "$work/SOURCES" "$work/srpm-result" "$work/keyring"
lock=inputs.module-check.lock.json
for kind in rpm key; do
    url=$(jq -er ".${kind}_url" "$lock")
    digest=$(jq -er ".${kind}_sha256" "$lock")
    [[ $url == https://* && $digest =~ ^[0-9a-f]{64}$ ]]
    target="$work/key.asc"
    [[ $kind != rpm ]] || target="$work/SOURCES/kernel-devel.rpm"
    curl -fsSL --proto '=https' --proto-redir '=https' "$url" -o "$target"
    printf '%s  %s\n' "$digest" "$target" | sha256sum --check --status
 done
rpm --dbpath "$work/keyring" --import "$work/key.asc"
rpmkeys --dbpath "$work/keyring" --checksig "$work/SOURCES/kernel-devel.rpm" | grep -F 'digests signatures OK'
release=$(jq -er .release "$lock")
rpm -qp --provides "$work/SOURCES/kernel-devel.rpm" | grep -Fx "kernel-devel-uname-r = $release"
printf '%s\n' "$release" >"$work/SOURCES/kernel-release"
(cd "$work/SOURCES"; sha256sum kernel-devel.rpm >kernel-devel.sha256)
id=$({ sha256sum packaging/bpi-m4-module-checks.spec "$lock"; } | sha256sum)
./scripts/build-srpm.bash "$repo/packaging/rpkg.conf" "$repo/packaging/bpi-m4-module-checks.spec" "$work" "${id:0:12}" server 1
mkdir -p out/srpms
srpms=("$work/srpm-result/"*.src.rpm)
cp "${srpms[0]}" out/srpms/module-checks.src.rpm
