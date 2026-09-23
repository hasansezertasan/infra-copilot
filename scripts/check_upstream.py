#!/usr/bin/env python3
"""Check the audited external versions in scripts/upstream.json.

Two independent checks, deliberately separated:

``--offline``
    Coherence. Every audited version must still appear in each document that
    cites it. No network, so this belongs in ``make check`` on every PR: it
    catches the manifest and the prose drifting apart.

default
    Freshness. Also fetches the current upstream release and reports any
    audited version that has fallen behind, and checks every HCP API path the
    shipped guidance calls against HCP's OpenAPI spec. Needs network, so it
    runs nightly.

The shipped references hardcode a lot of external fact. Nothing checked any of
it, and the failure mode is the worst kind for this repository: an agent follows
a documented step, the tool behaves differently than described, and the human is
mid-bootstrap unable to tell a mistake from a stale doc.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts/upstream.json"
REFERENCES = ROOT / "skills/infra-copilot/references"
TIMEOUT_SECONDS = 20


def load_entries(manifest: Path = MANIFEST) -> list[dict[str, object]]:
    with manifest.open(encoding="utf-8") as source:
        return list(json.load(source)["entries"])


def load_api_paths(manifest: Path = MANIFEST) -> dict[str, object]:
    with manifest.open(encoding="utf-8") as source:
        return dict(json.load(source)["api_paths"])


def cited_strings(entry: dict[str, object]) -> list[tuple[str, int]]:
    """The exact strings that must appear in the cited documents, with counts.

    Defaults to ``audited``, but a bare major like ``"5"`` is not searchable — it
    matches a numbered step or ``Terraform 1.5+`` — so an entry can declare
    ``cited_as`` with something distinctive instead. Where a document carries
    both an executed value and a human-readable one, such as an action pinned by
    commit SHA with the version in a comment, list both: they must move together.

    An item may be ``{"text": ..., "count": n}`` to require an exact number of
    occurrences. A plain membership test passes once *one* of several mentions is
    updated, leaving the rest stale — ``docs/import.md`` cites ``0.27.0`` four
    times in independently meaningful places. Requiring the count means a
    partial edit fails, and adding a legitimate new mention forces a deliberate
    manifest update rather than silently widening what goes unchecked.
    """
    declared = entry.get("cited_as") or [str(entry["audited"])]
    needles: list[tuple[str, int]] = []
    for value in declared:  # type: ignore[union-attr]
        if isinstance(value, dict):
            needles.append((str(value["text"]), int(value.get("count", 0))))
        else:
            needles.append((str(value), 0))  # 0 = at least one
    return needles


def occurrences(needle: str, text: str) -> int:
    """Count ``needle`` in ``text``, rejecting matches inside a longer version.

    A plain substring test accepts a prefix: ``1.2.3`` is present in ``1.2.30``,
    so a documented version could change and still read as coherent.
    """
    # Guard only the edges that are actually numeric. Applying the boundary
    # unconditionally breaks a needle whose text edge sits next to a period —
    # "v5 provider." reads as a failed lookahead rather than a match.
    # `-` and `+` continue a version too: without them, "0.27.0" matches inside
    # "0.27.0-rc.1", so a pin could change to a prerelease and still read as coherent.
    before = r"(?<![0-9.])" if needle[:1].isdigit() or needle.startswith(".") else ""
    after = r"(?![0-9.+-])" if needle[-1:].isdigit() or needle.endswith(".") else ""
    return len(re.findall(before + re.escape(needle) + after, text))


def check_linkage(entries: list[dict[str, object]]) -> list[str]:
    """At least one cited string must contain the audited version.

    ``cited_as`` replaces ``audited`` for searching, so without this the two
    checks can go green independently: bump ``audited`` to the new upstream
    version, forget the documents and ``cited_as``, and freshness passes
    against the new value while coherence passes against the old citation.
    """
    errors: list[str] = []
    for entry in entries:
        audited = str(entry["audited"])
        needles = [needle for needle, _count in cited_strings(entry)]
        # Bounded, like coherence: a substring test accepts "1.2.3" inside "v1.2.30",
        # so linkage would pass while the citation named a different version.
        if not any(occurrences(audited, needle) for needle in needles):
            errors.append(
                f"{entry['name']}: no cited_as string contains the audited version "
                f"{audited!r} ({', '.join(repr(n) for n in needles)}); the citation and "
                "the audited version must move together"
            )
    return errors


def check_coherence(entries: list[dict[str, object]], references: Path = REFERENCES) -> list[str]:
    """Every cited string must still appear in every document that cites it."""
    errors: list[str] = []
    for entry in entries:
        for relative in entry["cited_in"]:  # type: ignore[union-attr]
            document = references / str(relative)
            if not document.is_file():
                errors.append(f"{entry['name']}: cited_in names {relative}, which does not exist")
                continue
            text = document.read_text(encoding="utf-8")
            for needle, expected in cited_strings(entry):
                found = occurrences(needle, text)
                if expected and found != expected:
                    errors.append(
                        f"{entry['name']}: {relative} contains {needle!r} {found} "
                        f"time(s), expected {expected}; update scripts/upstream.json "
                        "or the document"
                    )
                elif not expected and not found:
                    errors.append(
                        f"{entry['name']}: {relative} no longer contains {needle!r}; "
                        "update scripts/upstream.json or the document"
                    )
    return errors


# Only the two spellings that name HCP by construction: the literal `api/v2` prefix and
# the `$hcp_api` variable steps.yaml defines. Prose like `POST /runs/<id>` is not
# scanned — the same form names GitHub's API elsewhere (`POST /app-manifests/...`), so
# picking it up would need a hand-kept list of which prose means which API.
# A path ends at anything that cannot be part of a segment in shell or Markdown; the
# query string is cut because the spec's `paths` never carry one.
API_PATH = re.compile(r"(?:api/v2|\$\{?hcp_api\}?)(/[^\s\"'`)|\\?#;,]*)")


def path_shape(path: str) -> str:
    """Reduce a path to its shape: literal segments kept, parameters as ``{}``.

    One function for both sides, so there is no mapping to maintain. A segment is a
    parameter if it interpolates anything — shell (``$ORG``, ``${ORG}``, ``$1``),
    placeholder prose (``<id>``), or an OpenAPI template (``{organization_name}``).
    """
    segments = [segment for segment in path.strip().rstrip(".:").split("/") if segment]
    return "/" + "/".join(
        "{}" if any(marker in segment for marker in "$<{") else segment
        for segment in segments
    )


def shape_matches(cited: str, spec: str) -> bool:
    """A cited shape is served by a spec shape of the same length.

    A cited literal may fill a spec parameter — ``workspaces/cloudflare`` is a
    ``{workspace_name}`` — but a cited parameter never matches a spec literal,
    because nothing guarantees the variable holds that one word.
    """
    cited_segments, spec_segments = cited.split("/"), spec.split("/")
    return len(cited_segments) == len(spec_segments) and all(
        ours == theirs or theirs == "{}"
        for ours, theirs in zip(cited_segments, spec_segments)
    )


def cited_api_paths(scan: list[str], root: Path = ROOT) -> dict[str, list[str]]:
    """Every HCP API path shape the shipped guidance calls, with where it is cited."""
    cited: dict[str, list[str]] = {}
    for relative in scan:
        base = root / relative
        files = sorted(base.rglob("*")) if base.is_dir() else [base]
        for document in files:
            if not document.is_file():
                continue
            try:
                text = document.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                for match in API_PATH.finditer(line):
                    shape = path_shape(match.group(1))
                    if shape == "/":
                        continue  # the bare base URL, e.g. `hcp_api: .../api/v2`
                    location = f"{document.relative_to(root).as_posix()}:{line_number}"
                    cited.setdefault(shape, []).append(location)
    return cited


def check_api_path_coherence(
    config: dict[str, object], root: Path = ROOT
) -> list[str]:
    """Offline: the scan still finds paths, and every ``unlisted`` path is still cited.

    An empty scan most likely means the pattern stopped matching how the guidance
    writes paths, which would turn the nightly into a check of nothing. A stale
    ``unlisted`` entry would silently excuse the path if it were ever reintroduced.
    """
    errors: list[str] = []
    cited = cited_api_paths(list(config["scan"]), root)  # type: ignore[arg-type]
    if not cited:
        errors.append(
            f"api_paths: no HCP API path found under {config['scan']}; the pattern in "
            "scripts/check_upstream.py no longer matches how the guidance writes them"
        )
    for item in config.get("unlisted", []):  # type: ignore[union-attr]
        shape = str(item["path"])  # type: ignore[index]
        if shape != path_shape(shape):
            errors.append(
                f"api_paths: unlisted path {shape!r} is not a shape; write {path_shape(shape)!r}"
            )
        if not str(item.get("evidence", "")).startswith("https://"):  # type: ignore[union-attr]
            errors.append(
                f"api_paths: unlisted path {shape!r} needs an https:// `evidence` link"
            )
        if shape not in cited:
            errors.append(
                f"api_paths: unlisted path {shape!r} is no longer cited; remove it from "
                "scripts/upstream.json"
            )
    return errors


def check_api_paths(
    cited: dict[str, list[str]], spec_paths: list[str], unlisted: list[str], spec_label: str
) -> list[str]:
    """Drift between the paths the guidance calls and the paths the spec lists.

    Reported for a human, never as proof of removal: the spec omits endpoints HCP's
    API docs describe — when this was written, the run ``discard`` and ``cancel``
    actions, and it lists some the docs do not.
    """
    spec_shapes = {path_shape(path) for path in spec_paths}

    def served(shape: str) -> bool:
        return any(shape_matches(shape, candidate) for candidate in spec_shapes)

    findings: list[str] = []
    for shape, locations in sorted(cited.items()):
        if shape in unlisted or served(shape):
            continue
        findings.append(
            f"api_paths: {shape} is not in {spec_label} (cited at {', '.join(locations)}). "
            "The spec is not exhaustive, so confirm against HCP's API docs: if the endpoint "
            "is gone, fix the guidance; if it is documented, add it to api_paths.unlisted "
            "with the docs link as evidence"
        )
    for shape in unlisted:
        if served(shape):
            findings.append(
                f"api_paths: unlisted path {shape} is now in {spec_label}; remove it from "
                "api_paths.unlisted so the spec covers it"
            )
    return findings


class Unreachable(RuntimeError):
    """The upstream version could not be read. Not the same as being stale."""


def fetch_json(url: str) -> dict[str, object]:
    """Fetch with curl, which steps.yaml's preflight already requires.

    Python's urllib depends on the interpreter having a usable CA bundle, which
    is not true of every developer install; curl is present wherever this
    repository's own toolchain check passes, so the network path stays
    verifiable locally instead of only in CI.
    """
    try:
        result = subprocess.run(
            ["curl", "-sSfL", "--max-time", str(TIMEOUT_SECONDS),
             "-H", "User-Agent: infra-copilot-upstream-check", url],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError as error:
        raise Unreachable("curl is not installed") from error
    except subprocess.CalledProcessError as error:
        raise Unreachable(f"curl failed: {error.stderr.strip() or error}") from error
    try:
        return dict(json.loads(result.stdout))
    except json.JSONDecodeError as error:
        raise Unreachable(f"response was not JSON: {error}") from error


def latest_version(source: dict[str, object]) -> str:
    """Current upstream version, normalised to bare digits and dots."""
    kind = source["type"]
    if kind == "github_release":
        tag = str(fetch_json(f"https://api.github.com/repos/{source['repo']}/releases/latest")["tag_name"])
    elif kind == "terraform_provider":
        url = f"https://registry.terraform.io/v1/providers/{source['namespace']}/{source['name']}"
        tag = str(fetch_json(url)["version"])
    else:
        raise ValueError(f"unknown source type {kind!r}")
    # Tags vary: v1.16.1, jq-1.8.2, 5.24.0.
    match = re.search(r"[0-9]+(?:\.[0-9]+)*", tag)
    if match is None:
        raise ValueError(f"no version found in tag {tag!r}")
    return match.group(0)


def fetch_release_file(source: dict[str, object]) -> tuple[str, dict[str, object]]:
    """A file as of the repository's latest release: (tag, parsed JSON).

    The release, not the default branch: go-tfe regenerates its spec on main every
    week or so, and a release is the version its maintainers stand behind. Reading
    the latest one rather than an audited pin is deliberate — the question is whether
    HCP serves a path today, and a pin would only add a bump with no decision attached.
    """
    repo = str(source["repo"])
    tag = str(fetch_json(f"https://api.github.com/repos/{repo}/releases/latest")["tag_name"])
    return tag, fetch_json(f"https://raw.githubusercontent.com/{repo}/{tag}/{source['path']}")


def check_api_paths_upstream(config: dict[str, object]) -> tuple[list[str], list[str]]:
    source = dict(config["source"])  # type: ignore[arg-type]
    try:
        tag, spec = fetch_release_file(source)
        spec_paths = list(dict(spec["paths"]))  # type: ignore[arg-type]
    except (Unreachable, KeyError, TypeError, ValueError) as error:
        return [], [f"api_paths: could not read {source.get('repo')}/{source.get('path')}: {error}"]
    cited = cited_api_paths(list(config["scan"]))  # type: ignore[arg-type]
    unlisted = [str(item["path"]) for item in config.get("unlisted", [])]  # type: ignore[union-attr,index]
    label = f"{source['repo']} {tag} {source['path']}"
    return check_api_paths(cited, spec_paths, unlisted, label), []


def resolve_tag_sha(repo: str, tag: str) -> str:
    """The commit a release tag points at, dereferencing annotated tags."""
    return str(fetch_json(f"https://api.github.com/repos/{repo}/commits/{tag}")["sha"])


def check_pinned_shas(entries: list[dict[str, object]]) -> tuple[list[str], list[str]]:
    """A cited SHA must be the commit its audited release tag resolves to.

    Otherwise a maintainer can bump ``audited`` and the version citation while
    leaving the old SHA in place: linkage is satisfied by the version citation,
    coherence still finds the old SHA, freshness compares only the version — and
    the shipped example keeps executing the previous action. Needs the network,
    because only the upstream repository knows what a tag points at.
    """
    findings: list[str] = []
    unreachable: list[str] = []
    for entry in entries:
        sha = entry.get("audited_sha")
        if not sha:
            continue
        source = dict(entry["source"])  # type: ignore[arg-type]
        tag = str(entry.get("tag_format", "v{audited}")).format(audited=entry["audited"])
        try:
            actual = resolve_tag_sha(str(source["repo"]), tag)
        except (Unreachable, KeyError) as error:
            unreachable.append(f"{entry['name']}: could not resolve {tag}: {error}")
            continue
        if actual != str(sha):
            findings.append(
                f"{entry['name']}: cited SHA {sha} is not what {tag} resolves to "
                f"({actual}); the pinned commit and the audited version disagree"
            )
    return findings, unreachable


def check_freshness(
    entries: list[dict[str, object]],
) -> tuple[list[str], list[str]]:
    """Return (drift, unreachable).

    Kept separate because an unreadable source proves nothing about staleness —
    reporting a rate limit as drift would send someone to review a document
    that is perfectly current.
    """
    findings: list[str] = []
    unreachable: list[str] = []
    for entry in entries:
        try:
            latest = latest_version(dict(entry["source"]))  # type: ignore[arg-type]
        except (Unreachable, ValueError, KeyError) as error:
            unreachable.append(f"{entry['name']}: {error}")
            continue
        audited = str(entry["audited"])
        current = latest.split(".")[0] if entry.get("compare") == "major" else latest
        if current != audited:
            cited = ", ".join(str(path) for path in entry["cited_in"])  # type: ignore[union-attr]
            findings.append(
                f"{entry['name']}: audited {audited}, upstream is now {current} "
                f"— review {cited} ({entry['why_it_matters']})"
            )
    return findings, unreachable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="only check that the docs still cite the audited versions",
    )
    arguments = parser.parse_args()

    entries = load_entries()
    api_paths = load_api_paths()
    errors = (
        check_linkage(entries) + check_coherence(entries) + check_api_path_coherence(api_paths)
    )
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if arguments.offline:
        if errors:
            return 1
        print(
            f"audited versions are still cited by their documents ({len(entries)} entries); "
            "HCP API paths found and every unlisted one still cited"
        )
        return 0

    findings, unreachable = check_freshness(entries)
    sha_findings, sha_unreachable = check_pinned_shas(entries)
    path_findings, path_unreachable = check_api_paths_upstream(api_paths)
    findings += sha_findings + path_findings
    unreachable += sha_unreachable + path_unreachable
    for finding in findings:
        print(f"DRIFT: {finding}", file=sys.stderr)
    for problem in unreachable:
        print(f"UNREACHABLE: {problem}", file=sys.stderr)
    if errors or findings:
        return 1
    if unreachable:
        # Distinct from 1: nothing was shown to be stale.
        return 2
    print(
        f"audited versions match upstream ({len(entries)} entries); "
        "cited HCP API paths are in the spec"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
