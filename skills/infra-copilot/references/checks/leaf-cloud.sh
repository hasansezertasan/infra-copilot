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
    }
    !incloud && line ~ /(^|[^[:alnum:]_])cloud[[:space:]]*{/ { incloud = 1 }
    incloud && (want == "hostname" || want == "organization") &&
        match(line, "(^|[^[:alnum:]_])" want "[[:space:]]*=[[:space:]]*\"[^\"]*\"") {
        value = substr(line, RSTART, RLENGTH)
        sub(/^[^"]*"/, "", value); sub(/"$/, "", value)
        print value; exit
    }
    incloud && line ~ /(^|[^[:alnum:]_])workspaces[[:space:]]*{/ { inws = 1 }
    inws && want == "workspace" && line ~ /(^|[^[:alnum:]_])tags[[:space:]]*=/ {
        print "TAGS"; exit
    }
    inws && want == "workspace" &&
        match(line, /(^|[^[:alnum:]_])name[[:space:]]*=[[:space:]]*"[^"]*"/) {
        value = substr(line, RSTART, RLENGTH)
        sub(/^[^"]*"/, "", value); sub(/"$/, "", value)
        print value; exit
    }
    inws && line ~ /}/ { inws = 0 }
    incloud && !inws && line ~ /}/ { incloud = 0 }
' "$leaf"/*.tf 2>/dev/null
