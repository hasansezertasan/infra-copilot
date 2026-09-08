#!/bin/sh
# Read Terraform cloud settings without mistaking comments or nested attributes
# for direct cloud members. `all` emits the settings consumed by hcp-apply-scope.
# Usage: leaf-cloud.sh <terraform/leaf> hostname|organization|workspace|token|all
set -u

[ "$#" -eq 2 ] || { echo "usage: leaf-cloud.sh <leaf> hostname|organization|workspace|token|all" >&2; exit 2; }
leaf=$1
want=$2
[ -d "$leaf" ] || exit 1
case "$want" in hostname|organization|workspace|token|all) : ;; *) exit 2 ;; esac

output=$(mktemp) || exit 2
trap 'rm -f "$output"' EXIT
: >"$output"
set -- "$leaf"/*.tf
if [ -f "$1" ]; then
awk -v want="$want" '
    function structural_depth_delta(text, copy, opens, closes) {
        copy = text
        gsub(/"[^"]*"/, "", copy)
        opens = gsub(/{/, "{", copy)
        closes = gsub(/}/, "}", copy)
        return opens - closes
    }
    function depth_through_match(text, copy) {
        copy = substr(text, 1, RSTART + RLENGTH - 1)
        return depth + structural_depth_delta(copy)
    }
    function emit(key, value) {
        if (want == "all") print key "=" value
        else if (want == key || (want == "workspace" && key == "workspaces.name")) {
            print value
            exit
        }
    }
    {
        opened_cloud = 0
        opened_workspace = 0
        line = $0
        while (incomment) {
            end = index(line, "*/")
            if (end == 0) { line = ""; break }
            line = substr(line, end + 2); incomment = 0
        }
        while ((start = index(line, "/*")) > 0) {
            rest = substr(line, start + 2)
            end = index(rest, "*/")
            if (end == 0) { line = substr(line, 1, start - 1); incomment = 1; break }
            line = substr(line, 1, start - 1) substr(rest, end + 2)
        }
        sub(/#.*/, "", line); sub(/\/\/.*/, "", line)
        structure = line
        gsub(/"[^"]*"/, "", structure)
    }
    !incloud && match(structure, /(^|[^[:alnum:]_])cloud[[:space:]]*{/) {
        incloud = 1
        opened_cloud = 1
        cloud_depth = depth_through_match(structure)
        if (want == "all") print "cloud=present"
    }
    incloud && !inws && match(structure, /(^|[^[:alnum:]_])workspaces[[:space:]]*{/) {
        inws = 1
        opened_workspace = 1
        workspace_depth = depth_through_match(structure)
    }
    incloud && !inws && (depth == cloud_depth || opened_cloud) {
        for (key = 1; key <= 2; key++) {
            attribute = (key == 1 ? "hostname" : "organization")
            if ((want == "all" || want == attribute) &&
                match(line, "(^|[^[:alnum:]_])" attribute "[[:space:]]*=[[:space:]]*\"[^\"]*\"")) {
                value = substr(line, RSTART, RLENGTH)
                sub(/^[^"]*"/, "", value); sub(/"$/, "", value)
                emit(attribute, value)
            }
        }
    }
    incloud && !inws && (depth == cloud_depth || opened_cloud) &&
        match(structure, /(^|[^[:alnum:]_])token[[:space:]]*=/) {
        emit("token", "present")
    }
    inws && (depth == workspace_depth || opened_workspace) &&
        line ~ /(^|[^[:alnum:]_])tags[[:space:]]*=/ {
        if (want == "workspace") { print "TAGS"; exit }
        if (want == "all") print "workspaces.tags=present"
    }
    inws && (depth == workspace_depth || opened_workspace) &&
        match(line, /(^|[^[:alnum:]_])name[[:space:]]*=[[:space:]]*"[^"]*"/) {
        value = substr(line, RSTART, RLENGTH)
        sub(/^[^"]*"/, "", value); sub(/"$/, "", value)
        emit("workspaces.name", value)
    }
    {
        depth += structural_depth_delta(structure)
        if (inws && depth < workspace_depth) inws = 0
        if (incloud && depth < cloud_depth) incloud = 0
    }
' "$@" >>"$output" 2>/dev/null || exit 2
fi

for json_file in "$leaf"/*.tf.json; do
    [ -f "$json_file" ] || continue
    jq -r --arg want "$want" '
      def clouds:
        .terraform.cloud?
        | select(. != null)
        | if type == "array" then .[] else . end;
      clouds as $cloud
      | if $want == "all" then
          "cloud=present",
          (if ($cloud.hostname | type) == "string" then "hostname=" + $cloud.hostname else empty end),
          (if ($cloud.organization | type) == "string" then "organization=" + $cloud.organization else empty end),
          (if ($cloud | has("token")) then "token=present" else empty end),
          (if ($cloud.workspaces | type) == "object" and ($cloud.workspaces | has("tags"))
             then "workspaces.tags=present" else empty end),
          (if ($cloud.workspaces.name | type) == "string"
             then "workspaces.name=" + $cloud.workspaces.name else empty end)
        elif $want == "workspace" then
          if ($cloud.workspaces | type) == "object" and ($cloud.workspaces | has("tags"))
          then "TAGS" else $cloud.workspaces.name // empty end
        elif $want == "token" then
          if ($cloud | has("token")) then "present" else empty end
        else $cloud[$want] // empty
        end' "$json_file" >>"$output" 2>/dev/null || exit 2
done

awk '!seen[$0]++' "$output"
