#!/usr/bin/bash
# Reconcile default package sources with the checked-in Git pull configuration.
set -Eeuo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$repo"
[[ $# == 0 ]] || { echo 'Usage: configure-copr-scm.bash (COPR_CLI may select the CLI)' >&2; exit 2; }
cli=${COPR_CLI:-copr-cli}
config=packaging/copr-scm.json
project=$(jq -er .project "$config")
url=$(jq -er .clone_url "$config")
commit=$(jq -er .committish "$config")
method=$(jq -er .method "$config")
existing=$("$cli" list-packages "$project")
while IFS=$'\t' read -r name spec; do
    action=add-package-scm
    if jq -e --arg name "$name" 'any(.[]; .name==$name)' <<<"$existing" >/dev/null; then
        action=edit-package-scm
    fi
    "$cli" "$action" "$project" --name "$name" --clone-url "$url" \
        --commit "$commit" --spec "$spec" --type git --method "$method" --webhook-rebuild off
done < <(jq -r '.packages[] | [.name,.spec] | @tsv' "$config")
