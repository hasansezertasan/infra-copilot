#!/bin/sh
# Read one value from a Terraform leaf's cloud block without mistaking comments,
# hostname, or an unrelated name attribute for the selected workspace.
# Usage: leaf-cloud.sh <terraform/leaf> hostname|organization|workspace
set -u

[ "$#" -eq 2 ] || { echo "usage: leaf-cloud.sh <leaf> hostname|organization|workspace" >&2; exit 2; }
leaf=$1
want=$2
[ -d "$leaf" ] || exit 1
case "$want" in hostname|organization|workspace) : ;; *) exit 2 ;; esac

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
    {
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
        cloud_depth = depth_through_match(structure)
    }
    incloud && (want == "hostname" || want == "organization") &&
        match(line, "(^|[^[:alnum:]_])" want "[[:space:]]*=[[:space:]]*\"[^\"]*\"") {
        value = substr(line, RSTART, RLENGTH)
        sub(/^[^"]*"/, "", value); sub(/"$/, "", value)
        print value; exit
    }
    incloud && !inws && match(structure, /(^|[^[:alnum:]_])workspaces[[:space:]]*{/) {
        inws = 1
        workspace_depth = depth_through_match(structure)
    }
    inws && want == "workspace" && line ~ /(^|[^[:alnum:]_])tags[[:space:]]*=/ {
        print "TAGS"; exit
    }
    inws && want == "workspace" &&
        match(line, /(^|[^[:alnum:]_])name[[:space:]]*=[[:space:]]*"[^"]*"/) {
        value = substr(line, RSTART, RLENGTH)
        sub(/^[^"]*"/, "", value); sub(/"$/, "", value)
        print value; exit
    }
    {
        depth += structural_depth_delta(structure)
        if (inws && depth < workspace_depth) inws = 0
        if (incloud && depth < cloud_depth) incloud = 0
    }
' "$leaf"/*.tf 2>/dev/null
