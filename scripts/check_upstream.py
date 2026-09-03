#!/usr/bin/env python3
"""Check the audited external versions in scripts/upstream.json.

Two independent checks, deliberately separated:

``--offline``
    Coherence. Every audited version must still appear in each document that
    cites it. No network, so this belongs in ``make check`` on every PR: it
    catches the manifest and the prose drifting apart.

default
    Freshness. Also fetches the current upstream release and reports any
    audited version that has fallen behind. Needs network, so it runs nightly.

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


def check_coherence(entries: list[dict[str, object]], references: Path = REFERENCES) -> list[str]:
    """Each audited version must appear in every document that cites it."""
    errors: list[str] = []
    for entry in entries:
        audited = str(entry["audited"])
        for relative in entry["cited_in"]:  # type: ignore[union-attr]
            document = references / str(relative)
            if not document.is_file():
                errors.append(f"{entry['name']}: cited_in names {relative}, which does not exist")
                continue
            if audited not in document.read_text(encoding="utf-8"):
                errors.append(
                    f"{entry['name']}: {relative} no longer mentions the audited "
                    f"version {audited}; update scripts/upstream.json or the document"
                )
    return errors


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
    errors = check_coherence(entries)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if arguments.offline:
        if errors:
            return 1
        print(f"audited versions are still cited by their documents ({len(entries)} entries)")
        return 0

    findings, unreachable = check_freshness(entries)
    for finding in findings:
        print(f"DRIFT: {finding}", file=sys.stderr)
    for problem in unreachable:
        print(f"UNREACHABLE: {problem}", file=sys.stderr)
    if errors or findings:
        return 1
    if unreachable:
        # Distinct from 1: nothing was shown to be stale.
        return 2
    print(f"audited versions match upstream ({len(entries)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
