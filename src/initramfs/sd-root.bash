# SPDX-License-Identifier: GPL-2.0-or-later
# Pure command-line parsing and read-only sysfs policy checks; shared with tests.
parse_root_partuuid() {
    local argument found=
    local -a arguments
    read -r -a arguments || return 1
    for argument in "${arguments[@]}"; do
        if [[ $argument == root=* ]]; then
            [[ -z $found && $argument == root=PARTUUID=* ]] || return 1
            found=${argument#root=PARTUUID=}
        fi
    done
    [[ $found =~ ^([[:xdigit:]]{8}-[[:xdigit:]]{2}|[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12})$ ]] || return 1
    printf '%s\n' "${found,,}"
}
verify_sd_policy() {
    local sys=$1 parameters=$2 partition=$3 disk=$4
    local start sectors capacity cid parameter
    [[ $disk =~ ^mmcblk[0-9]+$ && $partition =~ ^${disk}p[0-9]+$ ]] || return 1
    start=$(cat "$sys/class/block/$partition/start") || return 1
    sectors=$(cat "$sys/class/block/$partition/size") || return 1
    capacity=$(cat "$sys/class/block/$disk/size") || return 1
    cid=$(cat "$sys/class/block/$disk/device/cid") || return 1
    [[ $start =~ ^[0-9]+$ && $sectors =~ ^[0-9]+$ && $capacity =~ ^[0-9]+$ && $cid =~ ^[[:xdigit:]]{32}$ ]] || return 1
    (( start > 0 && sectors > 0 && start < capacity && sectors <= capacity - start )) || return 1
    [[ $(cat "$parameters/scratch_start") == "$start" ]] || return 1
    [[ $(cat "$parameters/scratch_sectors") == "$sectors" ]] || return 1
    [[ $(cat "$parameters/read_capacity") == "$capacity" ]] || return 1
    [[ $(cat "$parameters/scratch_cid") == "$cid" && $(cat "$parameters/read_cid") == "$cid" ]] || return 1
    for parameter in write_enable native_write native_read; do
        [[ $(cat "$parameters/$parameter") == Y ]] || return 1
    done
}
