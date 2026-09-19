#!/usr/bin/env python3
"""Validate portable skill links and host adapter metadata."""

from __future__ import annotations

import json
import posixpath
import re
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import NamedTuple
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRECTORIES = {".git", "node_modules"}
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
SKILL_FRONTMATTER = re.compile(
    r"\A---\s*\n(?P<body>.*?)\n---\s*\n", re.DOTALL
)
# Task is what lets a command reach the infra-auditor subagent, and ONLY
# `/infra-status` may: the shared protocol requires the action skills to run their
# resume scan inline, because the auditor's runbook substitutes for the checks that
# touch the working tree. Granting it to them would hand three commands a capability
# their own instructions forbid them to use -- the AskUserQuestion defect these
# checks exist for, in reverse.
COMMAND_TOOLS = {
    "infra-add.md": "Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion",
    "infra-import.md": "Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion",
    "infra-setup.md": "Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion",
    "infra-status.md": "Read, Bash, Glob, Grep, Task",
}
CONFIG_PATH = ".infra-copilot/config.md"
LEGACY_CONFIG_PATH = ".claude/infra-copilot.local.md"
CONFIG_FALLBACK_DOCUMENTS = (
    ".ai-rulez/commands/infra-setup.md",
    ".ai-rulez/commands/infra-status.md",
    ".ai-rulez/skills/setup/SKILL.md",
    ".ai-rulez/skills/status/SKILL.md",
    ".ai-rulez/skills/infra-copilot/references/protocol.md",
)
CUSTOMIZATION_TOKEN = "infra-copilot:customization"
# The scaffolded files a human is told to edit, each mapped to content the marker
# pair must *enclose*. A balanced pair is not enough: markers that sit together
# above the frontmatter are balanced and in order while enclosing nothing, so a
# re-scaffold would preserve an empty region and overwrite every real value.
# These are the fields that would be lost, so they are what gets asserted.
#
# Only content a rule cannot derive is listed here. Every top-level frontmatter
# key is required inside the region automatically -- enumerating them invites
# exactly the drift the markers guard against, since a field added to the
# template later would be silently unprotected.
#
# Each document also declares the exact comment form its markers must take and
# whether they have to sit inside YAML frontmatter. The token alone is not
# enough on either count: a marker that loses its "#" stops being a comment and
# becomes a stray line among the fields, and a start marker moved above the
# opening "---" leaves a document whose YAML block is no longer frontmatter at
# all -- both of which passed while validation stayed green.
class CustomizationRules(NamedTuple):
    marker: re.Pattern[str]
    enclosed: tuple[str, ...]
    in_frontmatter: bool


MARKER_EDGE = re.compile(
    rf"{re.escape(CUSTOMIZATION_TOKEN)}\s+(?:start|end)\b"
)


def _looks_like_marker(line: str) -> bool:
    """Whether a line is attempting to be a marker, however badly.

    Prose that merely mentions the token does not count, so a sentence
    explaining the markers is not read as a broken one.
    """
    stripped = line.strip()
    if stripped.startswith(CUSTOMIZATION_TOKEN):
        # An edge is required here too. Without it, prose that merely opens with
        # the token -- "infra-copilot:customization comments delimit user
        # values." -- was reported as a malformed marker and blocked the check.
        return MARKER_EDGE.match(stripped) is not None
    for prefix in ("<!--", "#"):
        if stripped.startswith(prefix):
            # Anchored to just after the prefix. Searching the whole comment
            # flagged explanatory prose that merely names the token and an edge
            # word, such as "<!-- Use infra-copilot:customization start ... -->".
            return MARKER_EDGE.match(stripped[len(prefix) :].lstrip()) is not None
    return False


def _marker_pattern(comment: str) -> re.Pattern[str]:
    """Full-line pattern for a marker in the given comment syntax."""
    token = re.escape(CUSTOMIZATION_TOKEN)
    if comment == "yaml":
        return re.compile(rf"^#\s*{token} (?P<edge>start|end)\s*$")
    return re.compile(rf"^<!--\s*{token} (?P<edge>start|end)\s*-->\s*$")


CUSTOMIZATION_DOCUMENTS = {
    ".ai-rulez/skills/infra-copilot/references/config.md.example": CustomizationRules(
        marker=_marker_pattern("yaml"),
        enclosed=(
            # Kept explicit on top of the derived keys: HCP regenerates this
            # after first VCS connect, so it is filled in long after the
            # scaffold and exists nowhere else. Naming it catches its outright
            # removal, which the derived rule cannot see.
            "hcp_status_check_id:",
        ),
        in_frontmatter=True,
    ),
    ".ai-rulez/skills/infra-copilot/references/decisions.md.example": (
        CustomizationRules(
            marker=_marker_pattern("html"),
            enclosed=("| Decision | Choice | Status | Rationale |",),
            in_frontmatter=False,
        )
    ),
}
# Where the preserve-or-hand-off rule is stated. The markers are inert without it:
# they are comments, so nothing enforces them but the documented rule.
CUSTOMIZATION_RULE_DOCUMENT = (
    ".ai-rulez/skills/infra-copilot/references/config.md"
)
CUSTOMIZATION_RULE_MARKERS = (
    "verbatim",
    "Never merge by inference",
)
PHASE_FIVE_RULE_DOCUMENT = (
    ".ai-rulez/skills/infra-copilot/references/status.md"
)
PHASE_FIVE_RULE_MARKERS = (
    # A clean run alone must never be read as "imports are done" ...
    "imports: 0",
    "incomplete",
    # ... but an applied run must count as done: applying does not rewrite the
    # stored plan, so its import actions remain listed forever.
    "status `applied`",
)
TOOLCHAIN_STEPS_DOCUMENT = ".ai-rulez/skills/infra-copilot/references/steps.yaml"
TOOLCHAIN_HCP_DOCUMENT = ".ai-rulez/skills/infra-copilot/references/hcp.md"
TOOLCHAIN_WORKSPACE_CHECK_DOCUMENT = (
    ".ai-rulez/skills/infra-copilot/references/checks/hcp-bootstrap-workspaces.sh"
)
TOOLCHAIN_SETUP_DOCUMENT = ".ai-rulez/skills/infra-copilot/references/docs/setup.md"
TOOLCHAIN_IMPORT_DOCUMENT = ".ai-rulez/skills/infra-copilot/references/docs/import.md"
TOOLCHAIN_CONFIG_DOCUMENT = ".ai-rulez/skills/infra-copilot/references/config.md"
TOOLCHAIN_STATUS_DOCUMENT = ".ai-rulez/skills/infra-copilot/references/status.md"
TOOLCHAIN_CI_DOCUMENT = ".ai-rulez/skills/infra-copilot/references/docs/ci.md"
TOOLCHAIN_DECISIONS_DOCUMENT = (
    ".ai-rulez/skills/infra-copilot/references/decisions.md.example"
)
JSON_MANIFESTS = (
    ".agents/plugins/marketplace.json",
    ".claude-plugin/marketplace.json",
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    "plugin.json",
)
MAKEFILE_PATH = "Makefile"
PACKAGE_JSON_PATH = "package.json"
# The tools package.json must pin. Listed here as well as there so deleting one
# from devDependencies fails loudly instead of quietly narrowing the check (#22);
# the two are asserted equal, so adding a tool means adding it in both places.
TOOL_PACKAGES = frozenset({"ai-rulez", "markdownlint-cli2", "skills"})
# The Makefile and the workflows call `node_modules/.bin/<tool>` and must not
# carry a version of their own; a second definition is exactly the drift this
# check exists to prevent.
TOOL_PIN_WORKFLOWS = (
    ".github/workflows/check.yml",
    ".github/workflows/release.yml",
    ".github/workflows/upstream.yml",
)
# The Makefile names each tool by the binary npm links into node_modules/.bin,
# which for all three equals the package name -- so a binary can be looked up in
# devDependencies directly. A tool whose binary differs fails the lookup, which
# is the right outcome: it needs a deliberate mapping, not a silent pass.
NODE_BIN_PATTERN = re.compile(r"node_modules/\.bin/(?P<binary>[A-Za-z0-9._-]+)")
# The directory named without a binary after it, which is how the check above
# gets blinded without anything appearing to change: `BIN := $(CURDIR)/node_
# modules/.bin` and then `$(BIN)/yaml` runs a tool no scan can see, because the
# path is only contiguous after make expands it. Resolving make variables would
# be a third grammar, so require the paths to stay written out instead -- the
# convention the Makefile already follows, now enforced rather than assumed.
NODE_BIN_UNNAMED = re.compile(r"node_modules/\.bin(?!/[A-Za-z0-9._-])")
# node_modules entries that are not the dot-directories npm maintains: reaching
# into a package's own files -- `node node_modules/yaml/bin.mjs` -- runs a
# transitive CLI without going through the .bin link the scan above reads. The
# dot-entries are ours to use (.bin holds the links, .install-stamp records the
# install); anything else is a package's internals and gets named as such.
NODE_MODULES_PACKAGE_PATH = re.compile(r"node_modules/(?![.])(?P<package>[^\s/]+)")
# Comments are NOT stripped: these files may not spell a pin in prose either.
#
# Stripping them meant deciding where a shell comment begins, and that produced
# five of the last six review rounds on this check -- which characters delimit a
# word, whether an escaped one still does, and the parity of a backslash run.
# Each fix was correct and the next edge case arrived anyway, because the
# question has a whole shell grammar behind it.
#
# The rule that replaces it costs nothing: no comment in this repository spells
# `<tool>@<version>` or a node_modules package path today, and none needs to --
# write `ai-rulez 4.11.3`, not `ai-rulez@4.11.3`. What was tolerated is now
# enforced, and an entire class of edge case stops existing rather than being
# handled correctly.
# Quoting and escaping are how the shell writes one word in pieces, so the pieces
# are put back together before the pin scan by dropping the delimiters -- no
# interpretation, since adjacent fragments are what concatenation is and a
# backslash before a character is that character.
#
# Bash has exactly five of these forms, and all five reduce to removing ' " \ $:
#
#   ai-rulez'@'4.9.0   ai-rulez"@"4.9.0   ai-rulez\@4.9.0
#   ai-rulez$'@'4.9.0  ai-rulez$"@"4.9.0
#
# each of which bash prints as ai-rulez@4.9.0.
#
# Removing delimiters is where this stops. It undoes quoting and escaping, which
# is syntax -- characters that mark a word without being in it. It does not
# decode escape *sequences*: `$'\x40'` is also `@` to bash, and reading it needs
# a table of \x, \0, \u and the C escapes, which is interpretation rather than
# removal. That is the line, and it is drawn here rather than at whichever
# sequence gets reported next.
#
# It holds because this guards against the habitual form coming back -- an old
# README line, a reflex `npx <tool>@<version>` -- not against someone determined
# to get past it. Anyone writing `$'\x40'` to dodge a check can edit
# package.json instead, and both are one reviewable diff.
SHELL_WORD_DELIMITERS = re.compile(r"""['"\\$]""")
# What this check enforces, and what it deliberately does not.
#
# Enforced, by substring and by data -- nothing here parses a language:
#   * devDependencies and TOOL_PACKAGES name the same tools, at exact versions;
#   * every node_modules/.bin binary the Makefile runs is a declared dependency;
#   * no Makefile or workflow names `<one of ours>@<version>`.
#
# Not enforced: a *fourth* tool fetched by a package runner -- `npx
# prettier@3.0.0` -- is not reported. A check for that has to decide what a file
# executes, and this repository's files are two languages deep: YAML whose
# quoting, comments and block scalars say which text is a command, and shell
# whose reserved words say where one begins. Seventeen review findings landed on
# successive attempts at that, each on the blind spot of the fix before it, and
# closing the class needs a YAML parser and a shell parser. validate.py is
# stdlib-only on purpose -- the Windows job runs it with no install step -- so it
# has neither, and a partial parser is what produced the seventeen.
#
# It costs little, because it was never the enforcement. A tool absent from
# package.json is never installed, so node_modules/.bin has no binary and the
# recipe fails on a real error rather than a predicted one; the three checks
# above still hold for the tools this repository actually pins, in any spelling,
# because a substring search needs no grammar. See PR #70 for the full history.
# Prerelease and build metadata are independent and may both appear:
# 0.3.0-rc.1+build.5 is one version, not a version plus trailing junk.
VERSION_PATTERN = r"[0-9]+(?:\.[0-9]+){2}(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"


def load_json(path: str, root: Path = ROOT) -> dict[str, object]:
    with (root / path).open(encoding="utf-8") as source:
        return json.load(source)


def validate_links(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    repository_root = root.resolve()
    for markdown in sorted(repository_root.rglob("*.md")):
        if IGNORED_DIRECTORIES.intersection(markdown.parts):
            continue
        relative_markdown = markdown.relative_to(repository_root).as_posix()
        text = markdown.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or target.startswith("#"):
                continue
            path_text = unquote(parsed.path)
            if not path_text:
                continue
            resolved = (markdown.parent / path_text).resolve()
            try:
                resolved.relative_to(repository_root)
            except ValueError:
                errors.append(
                    f"{relative_markdown}: link "
                    f"{raw_target!r} resolves outside the repository"
                )
                continue
            if not resolved.exists():
                errors.append(
                    f"{relative_markdown}: broken link {raw_target!r}"
                )
    return errors


def validate_skills() -> list[str]:
    errors: list[str] = []
    for skill in sorted((ROOT / ".ai-rulez/skills").glob("*/SKILL.md")):
        match = SKILL_FRONTMATTER.match(skill.read_text(encoding="utf-8"))
        relative = skill.relative_to(ROOT)
        if match is None:
            errors.append(f"{relative}: missing YAML frontmatter")
            continue
        body = match.group("body")
        name_match = re.search(r"^name:\s*([^\s]+)", body, re.MULTILINE)
        description_match = re.search(
            r'^description:\s*(?:"(?P<quoted>.*)"|(?P<plain>\S.*))$',
            body,
            re.MULTILINE,
        )
        if name_match is None:
            errors.append(f"{relative}: missing skill name")
        else:
            name = name_match.group(1).strip("\"'")
            if name != skill.parent.name:
                errors.append(
                    f"{relative}: skill name {name!r} must match its directory"
                )
            if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) is None:
                errors.append(f"{relative}: invalid portable skill name {name!r}")
        if description_match is None:
            errors.append(f"{relative}: missing skill description")
        else:
            description = description_match.group("quoted") or description_match.group(
                "plain"
            )
            if not 1 <= len(description) <= 1024:
                errors.append(
                    f"{relative}: description length {len(description)} is outside 1..1024"
                )
    return errors


MAX_DESCRIPTION_BUDGET = 2000


def skill_descriptions(root: Path = ROOT) -> dict[str, str]:
    """Every skill's frontmatter description, keyed by skill name."""
    found: dict[str, str] = {}
    for skill in sorted((root / ".ai-rulez/skills").glob("*/SKILL.md")):
        match = SKILL_FRONTMATTER.match(skill.read_text(encoding="utf-8"))
        if match is None:
            continue
        description = re.search(
            r'^description:\s*(?:"(?P<quoted>.*)"|(?P<plain>\S.*))$',
            match.group("body"),
            re.MULTILINE,
        )
        if description is None:
            continue
        # Key by the declared name, falling back to the directory. validate_skills
        # enforces that they match, but this helper should not depend on that check
        # having run to key the way its docstring says it does.
        name = re.search(r"^name:\s*(\S+)", match.group("body"), re.MULTILINE)
        key = name.group(1).strip("\"'") if name else skill.parent.name
        found[key] = description.group("quoted") or description.group("plain")
    return found


def validate_description_budget(root: Path = ROOT) -> list[str]:
    """Descriptions load into the host prompt every session, used or not.

    An aggregate budget prices the real resource — session context — rather
    than capping each skill, so a genuinely ambiguous skill can spend more as
    long as another spends less. The four action skills once carried enumerated
    trigger-phrase lists totalling 3.7 KB; the SessionStart hook now covers
    "this plugin exists", leaving descriptions to answer only "which skill".
    """
    total = sum(len(value) for value in skill_descriptions(root).values())
    if total > MAX_DESCRIPTION_BUDGET:
        return [
            f".ai-rulez/skills: description budget {total} > "
            f"{MAX_DESCRIPTION_BUDGET}; shorten SKILL.md frontmatter descriptions"
        ]
    return []


REQUIRED_SECTIONS = ("workflow", "guardrails", "validation", "example")
#: The router selects a skill and performs no work, so it has nothing to demonstrate.
SECTION_EXEMPTIONS = {"infra-copilot": {"example"}}


def validate_skill_sections(root: Path = ROOT) -> list[str]:
    """Every skill states its procedure, its limits, its done-condition, and one example.

    Matching is deliberately lenient — any H2 mentioning the word counts, so
    `## Example report` satisfies `example` — because the goal is that each
    concern is addressed somewhere findable, not that headings be identical.

    Before this existed the four action skills had four different shapes: the
    same concept was `Done signal` in one and `Success signal` in another, two
    had no completion section at all, and `status` buried its read-only
    contract inside an 86-line procedure.
    """
    errors: list[str] = []
    for skill in sorted((root / ".ai-rulez/skills").glob("*/SKILL.md")):
        name = skill.parent.name
        headings = re.findall(r"^##\s+(.*)$", skill.read_text(encoding="utf-8"), re.MULTILINE)
        lowered = " ".join(headings).lower()
        for section in REQUIRED_SECTIONS:
            if section in SECTION_EXEMPTIONS.get(name, set()):
                continue
            if not re.search(rf"\b{section}s?\b", lowered):
                errors.append(
                    f".ai-rulez/skills/{name}/SKILL.md: no H2 mentioning {section!r}"
                )
    return errors


def validate_command_tools() -> list[str]:
    errors: list[str] = []
    for filename, expected in COMMAND_TOOLS.items():
        command = ROOT / ".ai-rulez/commands" / filename
        match = SKILL_FRONTMATTER.match(command.read_text(encoding="utf-8"))
        actual_match = (
            re.search(r"^allowed-tools:\s*(.+)$", match.group("body"), re.MULTILINE)
            if match
            else None
        )
        actual = actual_match.group(1).strip() if actual_match else None
        if actual != expected:
            errors.append(
                f"{command.relative_to(ROOT)}: allowed-tools {actual!r} != {expected!r}"
            )
    return errors


def validate_config_fallbacks(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for relative in CONFIG_FALLBACK_DOCUMENTS:
        document = root / relative
        text = document.read_text(encoding="utf-8")
        for config_path in (CONFIG_PATH, LEGACY_CONFIG_PATH):
            if config_path not in text:
                errors.append(
                    f"{relative}: missing config-path guidance for {config_path!r}"
                )
    return errors


def read_document(path: Path) -> str | None:
    """Text of ``path``, or None when it cannot be read.

    Validators accumulate errors into one list, so an unguarded read raises
    before ``main`` can print any of them -- including the missing-artifact
    diagnostic that names the very file that failed to open.
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


FRONTMATTER_KEY = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*):")


# CommonMark: a fence opens on three or more backticks or tildes indented at most
# three spaces. Four spaces makes it an indented code block, not a fence.
# A line whose first non-space characters open a code fence. Detected, never
# interpreted: these two templates are forbidden from containing one.
#
# Earlier versions tracked fence and HTML-comment state to decide whether a
# marker was inside a code block. Five rounds of review found five defects in
# that tracking -- fence length, info strings, comment delimiters, close-and-
# reopen, inline code -- because deciding it correctly means implementing
# Markdown. These are two short templates that have never needed a fenced
# block, so the ambiguity is banned rather than resolved. A contributor who
# genuinely needs one gets a clear message instead of a wrong answer.
FENCE_DELIMITER = re.compile(r"^\s*(?:`{3,}|~{3,})")


def frontmatter_bounds(lines: list[str]) -> tuple[int, int] | None:
    """Indices of the opening and closing ``---``, or None if absent.

    Frontmatter has to start at line 0 -- that is what makes it frontmatter
    rather than a YAML block sitting in a markdown body -- and both delimiters
    have to start at column 0. Indented by four spaces, Markdown reads the
    block as an indented code span, so the document has no frontmatter at all
    while ``strip()`` still sees a ``---``.
    """
    if not lines or lines[0].rstrip() != "---":
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip() == "---":
            return 0, index
    return None


def frontmatter_keys(lines: list[str]) -> list[str]:
    """Top-level YAML keys in a document's frontmatter, or [] if it has none.

    Every one of these is a value a human fills in, so every one has to sit
    inside the preserved region. Deriving them means a field added to the
    template later is protected without anyone remembering to list it.
    """
    if not lines or lines[0].strip() != "---":
        return []
    keys: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = FRONTMATTER_KEY.match(line)
        if match:
            keys.append(match.group("key"))
    return keys


def validate_customization_markers(root: Path = ROOT) -> list[str]:
    """Both scaffolded files must carry one balanced customization pair.

    The markers are comments, so no parser enforces them; this is the only
    thing standing between a template edit and a re-scaffold that silently
    overwrites a hand-filled ``hcp_status_check_id``. Order is checked too --
    an end before a start reads as balanced if you only count.
    """
    errors: list[str] = []
    for relative, rules in CUSTOMIZATION_DOCUMENTS.items():
        text = read_document(root / relative)
        if text is None:
            # validate_layout reports the missing artifact, but it builds the same
            # error list this runs in, so raising here would hide its diagnostic
            # behind a traceback.
            errors.append(f"{relative}: unreadable, cannot check markers")
            continue
        lines = text.splitlines()
        edges: dict[str, list[int]] = {"start": [], "end": []}
        malformed: list[int] = []
        indented: list[int] = []
        # Refuse the whole document rather than guess what a fence encloses.
        # A fence anywhere can neutralise the markers, the required content, or
        # both, and telling which needs a Markdown parser.
        fences = [
            index
            for index, line in enumerate(lines)
            if FENCE_DELIMITER.match(line)
        ]
        if fences:
            errors.extend(
                f"{relative}: line {index + 1} opens or closes a code fence; "
                "this template may not contain fenced blocks, because whether "
                "a fence neutralises the markers cannot be decided without a "
                "Markdown parser"
                for index in fences
            )
            continue
        for index, line in enumerate(lines):
            # rstrip only. Leading whitespace is significant: indented four
            # spaces, Markdown reads the region as a code block, so the markers
            # become displayed text and the config block stops being
            # frontmatter -- both of which passed while strip() hid the indent.
            match = rules.marker.match(line.rstrip())
            if match:
                edges[match.group("edge")].append(index)
            elif rules.marker.match(line.strip()):
                indented.append(index)
            elif _looks_like_marker(line):
                # A line trying to be a marker but failing this file's syntax.
                # Reported separately: "found 0 start" would be a confusing way
                # to say "your marker lost its # and is now a bare line".
                #
                # Deliberately narrow. Both templates explain the markers in
                # prose that names the token in backticks, and matching the
                # bare token flagged those sentences.
                malformed.append(index)
        if indented:
            # Reported apart from malformed: the marker is correct, only its
            # column is wrong, and "not a well-formed comment marker" would
            # send the reader looking for a typo that is not there.
            errors.extend(
                f"{relative}: {CUSTOMIZATION_TOKEN} marker on line {index + 1} "
                "is indented; markers must start at column 0, or Markdown reads "
                "the region as a code block"
                for index in indented
            )
            continue
        if malformed:
            errors.extend(
                f"{relative}: line {index + 1} carries {CUSTOMIZATION_TOKEN} but is "
                f"not a well-formed comment marker: {lines[index].strip()!r}"
                for index in malformed
            )
            continue
        starts, ends = edges["start"], edges["end"]
        if len(starts) != 1 or len(ends) != 1:
            errors.append(
                f"{relative}: expected exactly one {CUSTOMIZATION_TOKEN} pair, "
                f"found {len(starts)} start and {len(ends)} end"
            )
            continue
        if starts[0] >= ends[0]:
            errors.append(
                f"{relative}: {CUSTOMIZATION_TOKEN} end precedes its start"
            )
            continue
        if rules.in_frontmatter:
            bounds = frontmatter_bounds(lines)
            if bounds is None:
                errors.append(
                    f"{relative}: no YAML frontmatter, so its markers cannot be "
                    "inside it"
                )
                continue
            opening, closing = bounds
            outside = [
                index
                for index in (starts[0], ends[0])
                if not opening < index < closing
            ]
            if outside:
                errors.extend(
                    f"{relative}: {CUSTOMIZATION_TOKEN} marker on line "
                    f"{index + 1} is outside the frontmatter delimiters "
                    f"(lines {opening + 1} and {closing + 1}), so the preserved "
                    "region no longer matches the fields a human fills in"
                    for index in outside
                )
                continue
        # Matched per line at column 0, not as a substring of the joined
        # region. An indented `hcp_status_check_id:` is a nested YAML key rather
        # than the field, so finding the text somewhere in the region is not
        # evidence that the field is there.
        region = [
            line.rstrip()
            for line in lines[starts[0] + 1 : ends[0]]
            if line[:1] not in (" ", "\t")
        ]
        required = (*rules.enclosed, *(f"{key}:" for key in frontmatter_keys(lines)))
        errors.extend(
            f"{relative}: {phrase!r} is outside the "
            f"{CUSTOMIZATION_TOKEN} region a re-scaffold preserves"
            for phrase in dict.fromkeys(required)
            if not any(phrase in line for line in region)
        )
    # Collapse whitespace: the rule is prose and re-wraps on edit, so matching the
    # raw text reports a phrase as missing purely because a line break moved.
    rule_text = read_document(root / CUSTOMIZATION_RULE_DOCUMENT)
    if rule_text is None:
        errors.append(f"{CUSTOMIZATION_RULE_DOCUMENT}: unreadable, cannot check rule")
        return errors
    rule = re.sub(r"\s+", " ", rule_text)
    errors.extend(
        f"{CUSTOMIZATION_RULE_DOCUMENT}: re-scaffold rule missing {marker!r}"
        for marker in CUSTOMIZATION_RULE_MARKERS
        if marker not in rule
    )
    return errors


def validate_phase_five_rule(root: Path = ROOT) -> list[str]:
    """Phase 5 completion must require an empty import set, not just a green run.

    A speculative run can finish cleanly while its plan still reports
    ``will be imported``, so status has to check the import count before calling
    the migration done.
    """
    text = (root / PHASE_FIVE_RULE_DOCUMENT).read_text(encoding="utf-8")
    return [
        f"{PHASE_FIVE_RULE_DOCUMENT}: phase-5 completion rule missing {marker!r}"
        for marker in PHASE_FIVE_RULE_MARKERS
        if marker not in text
    ]


UPSTREAM_MANIFEST = "scripts/upstream.json"


def audited_version(name: str, root: Path = ROOT) -> str:
    """The audited version of one entry in scripts/upstream.json.

    That file is the single authority for external versions cited in shipped
    guidance. Any other check needing one reads it from here rather than
    repeating the literal, so a drift update has exactly one place to change.
    """
    with (root / UPSTREAM_MANIFEST).open(encoding="utf-8") as source:
        entries = json.load(source)["entries"]
    for entry in entries:
        if entry["name"] == name:
            return str(entry["audited"])
    raise KeyError(f"{UPSTREAM_MANIFEST} has no entry named {name!r}")


def validate_toolchain_contract(root: Path = ROOT) -> list[str]:
    """Pins must come from the committed file and reach every HCP workspace."""
    errors: list[str] = []
    steps = (root / TOOLCHAIN_STEPS_DOCUMENT).read_text(encoding="utf-8")
    hcp = (root / TOOLCHAIN_HCP_DOCUMENT).read_text(encoding="utf-8")
    workspace_check_path = root / TOOLCHAIN_WORKSPACE_CHECK_DOCUMENT
    workspace_check = (
        workspace_check_path.read_text(encoding="utf-8")
        if workspace_check_path.is_file()
        else ""
    )
    setup = (root / TOOLCHAIN_SETUP_DOCUMENT).read_text(encoding="utf-8")
    import_guide = (root / TOOLCHAIN_IMPORT_DOCUMENT).read_text(encoding="utf-8")
    config = (root / TOOLCHAIN_CONFIG_DOCUMENT).read_text(encoding="utf-8")
    status = (root / TOOLCHAIN_STATUS_DOCUMENT).read_text(encoding="utf-8")
    ci = (root / TOOLCHAIN_CI_DOCUMENT).read_text(encoding="utf-8")
    decisions = (root / TOOLCHAIN_DECISIONS_DOCUMENT).read_text(encoding="utf-8")

    preflight_check = re.search(
        r"^  - tool: mise\n    check: >-\n(?P<body>(?:      .*\n)+)",
        steps,
        re.MULTILINE,
    )
    bootstrap_step = re.search(
        r"^  - id: toolchain-pin\n(?P<metadata>(?:(?!^  - id:).*(?:\n|\Z))*)",
        steps,
        re.MULTILINE,
    )
    repo_sync_step = re.search(
        r"^  - id: repo-config-sync\n(?P<metadata>(?:(?!^  - id:).*(?:\n|\Z))*)",
        steps,
        re.MULTILINE,
    )
    steps_start = steps.find("\nsteps:\n")
    first_step = (
        re.search(r"^  - id: ([^\n]+)", steps[steps_start:], re.MULTILINE)
        if steps_start >= 0
        else None
    )
    if (
        bootstrap_step is None
        or first_step is None
        or first_step.group(1) != "toolchain-pin"
    ):
        errors.append(
            f"{TOOLCHAIN_STEPS_DOCUMENT}: toolchain-pin must be the first phase-0 step"
        )
    elif not all(
        marker in bootstrap_step.group("metadata")
        for marker in (
            "    phase: 0\n",
            "    provider: repo\n",
            "    actor: HUMAN\n",
            "    produces: committed mise.toml + mise.lock\n",
            "    docs: docs/setup.md#6-local-development\n",
        )
    ):
        errors.append(
            f"{TOOLCHAIN_STEPS_DOCUMENT}: toolchain-pin metadata is incomplete"
        )
    if repo_sync_step is None or not all(
        marker in repo_sync_step.group("metadata")
        for marker in (
            "    phase: 0\n",
            "    provider: repo\n",
            "    actor: HUMAN\n",
            "test ! -x ./scripts/sync-config.sh || test ! -f .infra-copilot/config.md",
            "git ls-files --error-unmatch .infra-copilot/config.md",
            "git diff --quiet HEAD -- .infra-copilot/config.md",
            "git diff --cached --quiet HEAD -- .infra-copilot/config.md",
            "for config_file in terraform/cloudflare/versions.tf terraform/github/versions.tf; do",
            'test -f "$config_file"',
            '^[[:space:]]*organization[[:space:]]*=[[:space:]]*\\\"$ORG\\\"[[:space:]]*$',
        )
    ):
        errors.append(
            f"{TOOLCHAIN_STEPS_DOCUMENT}: repo-config-sync contract is incomplete"
        )
    if preflight_check is None:
        errors.append(
            f"{TOOLCHAIN_STEPS_DOCUMENT}: missing mise preflight check"
        )
    elif bootstrap_step is not None:
        step_check = re.search(
            r"^    check: >-\n(?P<body>(?:      .*\n)+)",
            bootstrap_step.group("metadata"),
            re.MULTILINE,
        )
        if (
            step_check is None
            or step_check.group("body") != preflight_check.group("body")
        ):
            errors.append(
                f"{TOOLCHAIN_STEPS_DOCUMENT}: toolchain-pin check must match the "
                "mise preflight check"
            )

    if "pin=$(mise current" in steps:
        errors.append(
            f"{TOOLCHAIN_STEPS_DOCUMENT}: reads active mise state instead of the "
            "committed pin"
        )
    for tool in ("terraform", "gh", "jq", "gcloud"):
        marker = f"mise config get --file ./mise.toml tools.{tool}"
        if marker not in steps:
            errors.append(
                f"{TOOLCHAIN_STEPS_DOCUMENT}: missing committed {tool} pin lookup"
            )
    for marker in (
        "git ls-files --error-unmatch mise.toml mise.lock",
        "git diff --quiet HEAD -- mise.toml mise.lock",
        "git diff --cached --quiet HEAD -- mise.toml mise.lock",
        'while IFS= read -r tool',
        '[ -z "$tool" ] && continue',
        'MISE_LOCKED=1 mise install --dry-run "$tool"',
    ):
        if marker not in steps:
            errors.append(f"{TOOLCHAIN_STEPS_DOCUMENT}: missing {marker!r}")
    if re.search(r"mise install[^\n]*\$pinned", steps):
        errors.append(
            f"{TOOLCHAIN_STEPS_DOCUMENT}: newline-delimited tool pins rely on "
            "shell-specific word splitting"
        )
    if '[ -n "$tool" ] && MISE_LOCKED=1' in steps or '[ -n "$tool" ] && MISE_LOCKED=1' in setup:
        errors.append(
            f"{TOOLCHAIN_STEPS_DOCUMENT}: tool-install loops must skip empty records "
            "explicitly"
        )
    if "mise config get --file ./mise.toml tools 2>/dev/null" not in steps:
        errors.append(
            f"{TOOLCHAIN_STEPS_DOCUMENT}: lock validation must enumerate the "
            "committed tool list instead of a fixed set"
        )
    # `core` is the core component's release date, not the SDK version, and
    # `value(core.version)` projects a field that does not exist — it returns empty, so
    # the check stayed red even when the installed SDK matched the pin.
    if "value(core.version)" in steps:
        errors.append(
            f"{TOOLCHAIN_STEPS_DOCUMENT}: gcloud check reads a nonexistent "
            "core.version field"
        )
    if '\'."Google Cloud SDK" // empty\'' not in steps:
        errors.append(
            f"{TOOLCHAIN_STEPS_DOCUMENT}: gcloud check must read the Google Cloud SDK "
            "version field"
        )
    if steps.count("grep -Eq '^[0-9]+\\.[0-9]+\\.[0-9]+") < 4:
        errors.append(
            f"{TOOLCHAIN_STEPS_DOCUMENT}: exact version checks are incomplete"
        )

    reconciliation = re.search(
        r"^  set_workspace_config \(\) \{(?P<body>.*?^  \})",
        hcp,
        re.MULTILINE | re.DOTALL,
    )
    if (
        hcp.count('"terraform-version"') < 3
        or reconciliation is None
        or not all(
            marker in reconciliation.group("body")
            for marker in (
                '"file-triggers-enabled":true',
                '"auto-destroy-at":null',
                '"auto-destroy-activity-duration":null',
                '"trigger-patterns":[$dir+"/**", "terraform/modules/**", ".infra-copilot/config.md", "mise.toml"]',
            )
        )
    ):
        errors.append(
            f"{TOOLCHAIN_HCP_DOCUMENT}: Terraform pin and trigger patterns must be "
            "created, reconciled, and verified"
        )
    for document, document_name in (
        (workspace_check, TOOLCHAIN_WORKSPACE_CHECK_DOCUMENT),
        (hcp, TOOLCHAIN_HCP_DOCUMENT),
    ):
        if (
            document.count(
                'index(".infra-copilot/config.md") != null'
            )
            < 1
            or document.count('index("terraform/modules/**") != null') < 1
            or document.count('index("mise.toml") != null') < 1
        ):
            errors.append(
                f"{document_name}: every HCP workspace must watch shared config and modules"
            )
    if 'checks/hcp-bootstrap-workspaces.sh' not in steps:
        errors.append(
            f"{TOOLCHAIN_STEPS_DOCUMENT}: workspace readiness must use the shared "
            "bootstrap-workspace check"
        )
    creation = re.search(
        r"^  create_ws \(\) \{(?P<body>.*?^  \})",
        hcp,
        re.MULTILINE | re.DOTALL,
    )
    if (
        creation is None
        or '"auto-destroy-at":null' not in creation.group("body")
        or '"auto-destroy-activity-duration":null' not in creation.group("body")
        or '"trigger-patterns":[$dir+"/**", "terraform/modules/**", ".infra-copilot/config.md", "mise.toml"]'
        not in creation.group("body")
    ):
        errors.append(
            f"{TOOLCHAIN_HCP_DOCUMENT}: workspace creation must include the shared "
            "config trigger"
        )
    if not re.search(r"^Phase 0.*\brepo-config-sync\b", status, re.MULTILINE):
        errors.append(
            f"{TOOLCHAIN_STATUS_DOCUMENT}: phase-0 report must include repo-config-sync"
        )

    review = setup.find("cat -- mise.toml")
    trust = setup.find("mise trust mise.toml")
    if review < 0 or trust < 0 or review > trust:
        errors.append(
            f"{TOOLCHAIN_SETUP_DOCUMENT}: mise.toml review must precede trust"
        )
    for marker in ("mise lock", "MISE_LOCKED=1 mise install"):
        if marker not in setup:
            errors.append(f"{TOOLCHAIN_SETUP_DOCUMENT}: missing {marker!r}")
    # Installing does not put the pinned tools on PATH, so the guide has to activate
    # them (or route through `mise exec`) before anything invokes a bare binary.
    install = setup.find("MISE_LOCKED=1 mise install")
    activate = setup.find("mise activate")
    if activate < 0 or "mise exec" not in setup or install > activate:
        errors.append(
            f"{TOOLCHAIN_SETUP_DOCUMENT}: installed toolchain must be activated "
            "before its binaries are invoked"
        )
    # A bare `mise install` resolves the merged config, so a tool in the developer's
    # user-level config that this repo never locked fails an otherwise valid setup.
    if re.search(r"MISE_LOCKED=1 mise install\s*$", setup, re.MULTILINE):
        errors.append(
            f"{TOOLCHAIN_SETUP_DOCUMENT}: locked install must name the repository's "
            "pinned tools instead of the merged config"
        )
    if "lockfile = true" in setup:
        errors.append(
            f"{TOOLCHAIN_SETUP_DOCUMENT}: unsupported lockfile setting is documented"
        )
    touch = setup.find("touch mise.lock")
    lock = setup.find("mise lock")
    if touch < 0 or lock < 0 or touch > lock:
        errors.append(
            f"{TOOLCHAIN_SETUP_DOCUMENT}: mise.lock must be initialized before locking"
        )
    # The version comes from scripts/upstream.json, which is the single authority for
    # audited external versions. Hardcoding it here made that manifest the second one:
    # resolving a cf-terraforming bump would pass check_upstream and still fail here,
    # with nothing pointing at this line.
    # main() evaluates every validator into one list, so raising here would replace the
    # errors already collected with a traceback. Report and keep going: an unreadable
    # manifest must not suppress the checks below it either.
    cf_version: str | None = None
    try:
        cf_version = audited_version("cf-terraforming", root)
    except (OSError, json.JSONDecodeError, KeyError) as error:
        errors.append(
            f"{UPSTREAM_MANIFEST}: cannot read the cf-terraforming pin: {error}"
        )
    markers = ["mise lock", "git add mise.toml mise.lock",
               'MISE_LOCKED=1 mise install "github:cloudflare/cf-terraforming"']
    if cf_version is not None:
        markers.append(f'"github:cloudflare/cf-terraforming" = "{cf_version}"')
    for marker in markers:
        if marker not in import_guide:
            errors.append(f"{TOOLCHAIN_IMPORT_DOCUMENT}: missing {marker!r}")
    # `mise use` installs as it writes the pin, which resolves the binary before the
    # lock covering it exists. The pin must be written, then locked, then installed.
    if re.search(r"^\s*mise use\b", import_guide, re.MULTILINE):
        errors.append(
            f"{TOOLCHAIN_IMPORT_DOCUMENT}: installs the pin before locking it"
        )
    import_lock = import_guide.find("mise lock")
    import_install = import_guide.find(
        'MISE_LOCKED=1 mise install "github:cloudflare/cf-terraforming"'
    )
    if import_lock < 0 or import_install < 0 or import_lock > import_install:
        errors.append(
            f"{TOOLCHAIN_IMPORT_DOCUMENT}: cf-terraforming must be locked before "
            "it is installed"
        )
    # cf-terraforming is pinned after setup activated the environment, so the new
    # binary is not on PATH and a system build would shadow it.
    if re.search(r"^\s*cf-terraforming ", import_guide, re.MULTILINE):
        errors.append(
            f"{TOOLCHAIN_IMPORT_DOCUMENT}: cf-terraforming must run through the "
            "pinned environment"
        )
    if '"$(which terraform)"' in import_guide:
        errors.append(
            f"{TOOLCHAIN_IMPORT_DOCUMENT}: terraform path must resolve through mise, "
            "not the outer shell"
        )
    # The lock check must reject floating selectors for every enumerated tool, not
    # just the four with dedicated per-tool checks below it.
    if "grep -Evq '^[0-9]+\\.[0-9]+\\.[0-9]+" not in steps:
        errors.append(
            f"{TOOLCHAIN_STEPS_DOCUMENT}: every configured pin must be an exact "
            "version"
        )
    # The toolchain decision claims parity with CI, so CI has to install from the
    # committed lock rather than choose its own Terraform.
    if "jdx/mise-action" not in ci:
        errors.append(
            f"{TOOLCHAIN_CI_DOCUMENT}: CI must install the repository-pinned toolchain"
        )
    if "in CI" in decisions and "docs/ci.md" not in decisions:
        errors.append(
            f"{TOOLCHAIN_DECISIONS_DOCUMENT}: the CI parity claim must point at the "
            "workflow that backs it"
        )
    if "export TERRAFORM_VERSION=$(mise config get" in config:
        errors.append(
            f"{TOOLCHAIN_CONFIG_DOCUMENT}: Terraform pin export runs before preflight"
        )
    if "Report `curl`\n   separately as present or missing" not in status:
        errors.append(
            f"{TOOLCHAIN_STATUS_DOCUMENT}: curl must be reported without pin state"
        )
    return errors


SHIPPED_REFERENCES = "skills/infra-copilot/references"
SHIPPED_CHECK_PATTERN = re.compile(r"\$INFRA_COPILOT_REFERENCES/(?P<path>[A-Za-z0-9._/-]+)")


def validate_shipped_check_paths(root: Path = ROOT) -> list[str]:
    """Every `$INFRA_COPILOT_REFERENCES/...` path must exist in the shipped tree.

    A check that names a renamed or deleted script fails at run time inside a
    consuming repo, where the diagnostic is a bare shell error. Catch it here.
    """
    errors: list[str] = []
    manifest = root / SHIPPED_REFERENCES / "steps.yaml"
    text = manifest.read_text(encoding="utf-8")
    references_root = (root / SHIPPED_REFERENCES).resolve()
    for match in SHIPPED_CHECK_PATTERN.finditer(text):
        relative = match.group("path")
        # The path comes out of a shell string, so it can be absolute or contain `..`.
        # `Path("a") / "/abs"` discards the prefix and `..` traverses upward, either of
        # which would test some unrelated location. Resolve and require containment,
        # matching validate_links and validate_manifest_paths.
        resolved = (references_root / relative).resolve()
        try:
            resolved.relative_to(references_root)
        except ValueError:
            errors.append(
                f"{SHIPPED_REFERENCES}/steps.yaml: check references "
                f"$INFRA_COPILOT_REFERENCES/{relative}, which resolves outside the "
                "shipped references tree"
            )
            continue
        # Either a script or a directory: the preflight guard tests `checks/` itself.
        if not resolved.exists():
            errors.append(
                f"{SHIPPED_REFERENCES}/steps.yaml: check references "
                f"$INFRA_COPILOT_REFERENCES/{relative}, which does not exist"
            )
    if SHIPPED_CHECK_PATTERN.search(text) and "infra-copilot-references" not in text:
        errors.append(
            f"{SHIPPED_REFERENCES}/steps.yaml: a check resolves a shipped script but "
            "preflight has no infra-copilot-references guard"
        )
    return errors


#: The shipped copy is what a user actually installs, so it is the one gated. ai-rulez
#: copies the whole references tree, and `verify --plugin` fails on drift from the source.
HOSTS_DOCUMENT = "skills/infra-copilot/references/hosts.md"
HOSTS_BASENAME = "hosts.md"
PROTOCOL_DOCUMENTS = (
    ".ai-rulez/skills/infra-copilot/references/protocol.md",
    "skills/infra-copilot/references/protocol.md",
)
INSTALL_GUIDE_GLOB = "install-*.md"
#: The section that gives the AskUserQuestion grant in commands/ a consumer.
DECISION_HEADING = "### Asking a decision"
#: A row is identified by having an install-guide cell; column 1 is the host and
#: column 2 the question tool. Everything between them is free, because hosts.md
#: invites new per-host columns (#19 subagent manifests, #42 hook paths) and a
#: pattern anchored to the last column would make every row unparseable the day one
#: is added -- reporting "no rows" about cells that are all present.
HOST_GUIDE_CELL = re.compile(r"\A`(docs/install-[a-z0-9-]+\.md)`\Z")
HOST_TOOL_CELL = re.compile(r"\A`([A-Za-z_][A-Za-z0-9_]*)`\Z")


def link_targets(document: str) -> set[str]:
    """Every local Markdown link target in ``document``, path only.

    The citation gates below used substring tests, which a bare mention in prose
    satisfied -- "See references/hosts.md" passed while the page carried no
    navigable link, so the one thing the gate exists to guarantee was absent.
    """
    targets: set[str] = set()
    for raw in MARKDOWN_LINK.findall(document):
        parsed = urlsplit(raw.strip().strip("<>"))
        if parsed.scheme or parsed.netloc:
            continue
        path = unquote(parsed.path)
        if path:
            targets.add(path)
    return targets


def cites_hosts_record(document: str) -> bool:
    """Whether ``document`` links the host record, as opposed to naming its path.

    One helper for every citation gate. The protocol's check was left as a substring
    test when the guide and README checks were tightened, so protocol.md could lose
    its link and keep the words -- the same near-miss, one file later.
    """
    return any(
        PurePosixPath(target).name == HOSTS_BASENAME
        for target in link_targets(document)
    )


def host_records(root: Path = ROOT) -> dict[str, tuple[str, str]]:
    """Each host row in hosts.md as ``host -> (question tool, install guide)``.

    The tool is empty when column 2 does not hold a backticked identifier;
    ``validate_host_contract`` reports that as its own error rather than letting the
    row vanish and resurface as an unrelated complaint about an orphan guide.
    """
    text = read_document(root / HOSTS_DOCUMENT)
    if text is None:
        return {}
    records: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        guides = [
            match.group(1)
            for match in (HOST_GUIDE_CELL.match(cell) for cell in cells)
            if match
        ]
        if not guides or len(cells) < 2:
            continue
        tool = HOST_TOOL_CELL.match(cells[1])
        records[cells[0]] = (tool.group(1) if tool else "", guides[0])
    return records


def decision_section(protocol: str) -> str | None:
    """The body of the decision section, or None when the heading is absent.

    Scoped rather than whole-document: the check exists so that deleting the rule
    fails here, and a tool named anywhere else in protocol.md -- the preflight, a
    later note -- would otherwise satisfy it for a document that no longer carries
    the rule at all.
    """
    start = protocol.find(DECISION_HEADING)
    if start < 0:
        return None
    body = protocol[start + len(DECISION_HEADING) :]
    following = re.search(r"^#{1,6} ", body, re.MULTILINE)
    return body[: following.start()] if following else body


def validate_host_contract(root: Path = ROOT) -> list[str]:
    """hosts.md is the only per-host record, and everything else cites it.

    Three documents independently grew per-host facts: the README install table, the
    protocol's human-interaction rules, and the command frontmatter that grants
    ``AskUserQuestion`` to three commands no document ever told to use it. This gates
    the arrangement that replaced them -- one table, cited rather than copied.

    What it can check is existence and citation, not truth: no host publishes a
    machine-readable capability record, so a wrong capability claim is only catchable
    by a session on that host. Citation is exactly the part that drifts silently,
    which is why it is the part with a gate.
    """
    errors: list[str] = []
    records = host_records(root)
    if len(records) < 2:
        return [
            f"{HOSTS_DOCUMENT}: no host capability rows parsed; each row needs a "
            "`tool` column and a `docs/install-*.md` column"
        ]

    guides = {guide for _, guide in records.values()}
    for host, (tool, guide) in sorted(records.items()):
        if not tool:
            errors.append(
                f"{HOSTS_DOCUMENT}: {host} has no question tool in column 2; it must "
                "be a backticked identifier such as `AskUserQuestion`"
            )
        document = read_document(root / guide)
        if document is None:
            errors.append(f"{HOSTS_DOCUMENT}: {host} names {guide}, which is missing")
            continue
        # Pointing back is what keeps the guide from becoming a second source of truth.
        # The link has to be a link: docs/ sits at a different depth from both copies
        # of the references tree, so a reader who cannot click it has to guess.
        if not cites_hosts_record(document):
            errors.append(
                f"{guide}: does not link references/hosts.md; per-host capabilities "
                "must be cited there, not restated here"
            )

    # An install guide absent from the table is a page nothing points at -- the
    # documented-but-nonexistent failure inverted, and just as invisible.
    for orphan in sorted((root / "docs").glob(INSTALL_GUIDE_GLOB)):
        relative = orphan.relative_to(root).as_posix()
        if relative not in guides:
            errors.append(f"{relative}: install guide is not listed in {HOSTS_DOCUMENT}")

    readme = read_document(root / "README.md")
    if readme is None:
        errors.append("README.md: unreadable, cannot check install-guide links")
    else:
        linked = link_targets(readme)
        errors.extend(
            f"README.md: install table does not link {guide}"
            for guide in sorted(guides)
            if guide not in linked
        )

    # #12: the AskUserQuestion grant in command frontmatter had no consumer. The
    # protocol now states when to use a native question tool; assert it still does,
    # so deleting that section fails here instead of silently orphaning the grant.
    # Matched on a word boundary and paired with the heading: one recorded tool is
    # named `question`, so a bare substring test would be satisfied by any prose in
    # protocol.md using the English word, and deleting the rule would pass.
    tools = {tool for tool, _ in records.values() if tool}
    named = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(tool) for tool in sorted(tools)))
    for relative in PROTOCOL_DOCUMENTS:
        protocol = read_document(root / relative)
        if protocol is None:
            errors.append(f"{relative}: unreadable, cannot check the question-tool rule")
            continue
        if not cites_hosts_record(protocol):
            errors.append(f"{relative}: does not link {HOSTS_BASENAME}")
        section = decision_section(protocol)
        if section is None:
            errors.append(f"{relative}: has no {DECISION_HEADING!r} section")
        elif not tools or not named.search(section):
            errors.append(
                f"{relative}: its {DECISION_HEADING!r} section names no question tool "
                f"from {HOSTS_DOCUMENT}; the allowed-tools grant in commands/ would "
                "have no consumer"
            )
    return errors


#: A skill depends on another when it reads that skill's references tree. The hub's
#: links to `../<skill>/SKILL.md` are routing, not dependency -- it hands off to a
#: skill it does not need installed -- so matching `references/` keeps the arrow
#: pointing the right way and the hub's closure at one node.
SKILL_DEPENDENCY = re.compile(r"\.\./(?P<skill>[a-z0-9-]+)/references/")
#: Skills that own no operations of their own. `infra-copilot` selects a workflow and
#: hands off, so installed alone it is a router with nothing to route to. They are
#: valid closure *members* -- that is the whole point of the hub -- but never roots.
#: Listed rather than derived: "nothing else depends on it" would also reject a future
#: skill that is legitimately both an entry point and a dependency.
ROUTER_SKILLS = frozenset({"infra-copilot"})


def skill_closure(name: str, root: Path = ROOT) -> list[str]:
    """``name`` plus every skill it needs, sorted.

    Derived from the links each SKILL.md already carries rather than declared in a
    manifest. A hand-written graph is a second place to state the same fact, and the
    links are the copy that breaks loudly -- validate_links already proves each
    target exists. A sixth skill declares its dependencies by linking them.
    """
    pending = [name]
    closure: set[str] = set()
    while pending:
        skill = pending.pop()
        if skill in closure:
            continue
        closure.add(skill)
        document = read_document(root / ".ai-rulez/skills" / skill / "SKILL.md")
        if document is None:
            continue
        pending.extend(
            match.group("skill") for match in SKILL_DEPENDENCY.finditer(document)
        )
    return sorted(closure)


def validate_json_manifests(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for relative in JSON_MANIFESTS:
        try:
            with (root / relative).open(encoding="utf-8") as source:
                json.load(source)
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{relative}: invalid JSON manifest: {error}")
    return errors


def collect_manifest_errors(root: Path = ROOT) -> list[str]:
    """Manifests must parse before path validation is allowed to read them.

    ``validate_manifest_paths`` indexes into the decoded manifests, so running it
    over malformed JSON raises instead of returning findings, and main() would exit
    on a traceback without printing the errors already collected.
    """
    parse_errors = validate_json_manifests(root)
    if parse_errors:
        return parse_errors
    return validate_manifest_paths(root)


def validate_manifest_paths(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    claude_marketplace = json.loads(
        (root / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
    )
    codex_plugin = json.loads(
        (root / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
    )
    codex_marketplace = json.loads(
        (root / ".agents/plugins/marketplace.json").read_text(encoding="utf-8")
    )
    configured_paths = (
        (
            ".claude-plugin/marketplace.json",
            str(claude_marketplace["plugins"][0]["source"]),
        ),
        (".codex-plugin/plugin.json", str(codex_plugin["skills"])),
        (
            ".agents/plugins/marketplace.json",
            str(codex_marketplace["plugins"][0]["source"]["path"]),
        ),
    )
    repository_root = root.resolve()
    for manifest, configured_path in configured_paths:
        destination = (repository_root / configured_path).resolve()
        try:
            destination.relative_to(repository_root)
        except ValueError:
            errors.append(
                f"{manifest}: path {configured_path!r} resolves outside the repository"
            )
            continue
        if not destination.exists():
            errors.append(f"{manifest}: path {configured_path!r} does not exist")
    return errors


def validate_tool_pins(root: Path = ROOT) -> list[str]:
    """package.json owns every tool version; nothing else may name one.

    Forwards: every ``node_modules/.bin`` binary the Makefile runs must be a
    declared dependency, so neither a fourth tool nor a transitive one can be
    used without an entry that Renovate then keeps current. Backwards: no
    Makefile or workflow may name ``<package>@<version>`` for a tool this
    repository pins, so the manifest stays the only definition rather than
    merely one of them. Both are substring scans over comment-stripped text and
    neither parses a language -- see the note above ``SHELL_WORD_DELIMITERS`` for what
    that deliberately does not cover.

    This replaces a README cross-check. The versions used to be Makefile literals
    restated in the README, which is why Renovate needed a custom manager
    scanning both files; with npm resolving them there is nothing to restate.
    """
    errors: list[str] = []
    try:
        manifest = load_json(PACKAGE_JSON_PATH, root)
    except (OSError, json.JSONDecodeError) as error:
        return [f"{PACKAGE_JSON_PATH}: cannot read the tool manifest: {error}"]
    declared = manifest.get("devDependencies")
    if not isinstance(declared, dict):
        return [f"{PACKAGE_JSON_PATH}: missing a devDependencies table"]

    for package in sorted(TOOL_PACKAGES - set(declared)):
        errors.append(f"{PACKAGE_JSON_PATH}: missing devDependency {package}")
    for package in sorted(set(declared) - TOOL_PACKAGES):
        errors.append(
            f"{package}: in {PACKAGE_JSON_PATH} but not TOOL_PACKAGES; "
            f"add it there so scripts/validate.py guards it too"
        )
    # Exact, not a range: a caret would let CI resolve a version no one reviewed,
    # which is the property the Makefile literals had and must not lose.
    for package, specifier in sorted(declared.items()):
        if not re.fullmatch(VERSION_PATTERN, str(specifier)):
            errors.append(
                f"{package}: {PACKAGE_JSON_PATH} pins {specifier!r}; "
                f"use an exact version, not a range"
            )

    # Read once, and report an unreadable file rather than raising out of an
    # aggregate validator: a traceback here would hide every other diagnostic.
    sources: dict[str, str] = {}
    for relative in (MAKEFILE_PATH, *TOOL_PIN_WORKFLOWS):
        try:
            sources[relative] = (root / relative).read_text(encoding="utf-8")
        except OSError as error:
            errors.append(f"{relative}: cannot read file: {error}")

    # The Makefile only. node_modules/.bin holds the transitive closure rather
    # than the manifest, so running one of those binaries pins nothing -- but a
    # workflow that merely *names* a path in a step label runs nothing either,
    # and telling those apart is the parsing this check no longer does. The
    # workflows call `make`, which is where the binaries actually are.
    makefile = sources.get(MAKEFILE_PATH, "")
    for package in sorted({
        match.group("package") for match in NODE_MODULES_PACKAGE_PATH.finditer(makefile)
    }):
        errors.append(
            f"{MAKEFILE_PATH}: reaches into node_modules/{package}; run tools "
            f"through node_modules/.bin/<tool> so this check can see them"
        )
    if NODE_BIN_UNNAMED.search(makefile):
        errors.append(
            f"{MAKEFILE_PATH}: names node_modules/.bin without a binary after it; "
            f"write each tool's path out in full so this check can see which "
            f"binaries run"
        )
    for binary in sorted(set(NODE_BIN_PATTERN.findall(makefile))):
        if binary not in declared:
            errors.append(
                f"{MAKEFILE_PATH}: runs {binary}, which no {PACKAGE_JSON_PATH} "
                f"devDependency provides"
            )

    for relative, text in sources.items():
        for package in sorted(TOOL_PACKAGES):
            # Any `<package>@…` reference, not just a literal version. One form
            # this replaced was indirect — `ai-rulez@${INFRA_COPILOT_..._VERSION}`
            # with the value in `env:` — so matching only a literal semver would
            # miss exactly the pattern being removed.
            #
            # A substring, so no quoting or nesting can hide it: this is the one
            # guarantee that survived every finding on PR #70, including the
            # cases that defeated the parsers.
            if re.search(rf"(?<![\w/-]){re.escape(package)}@", SHELL_WORD_DELIMITERS.sub("", text)):
                errors.append(
                    f"{relative}: invokes {package}@… directly; "
                    f"run node_modules/.bin/{package} so {PACKAGE_JSON_PATH} "
                    f"stays the only definition"
                )
    return errors


def toml_string(path: str, table: str, key: str, root: Path = ROOT) -> str:
    text = (root / path).read_text(encoding="utf-8")
    section = re.search(
        rf"^\[{re.escape(table)}\]\s*$\n(?P<body>.*?)(?=^\[|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if section is None:
        raise ValueError(f"{path}: missing [{table}] table")
    value = re.search(
        rf"^\s*{re.escape(key)}\s*=\s*['\"](?P<value>[^'\"]+)['\"]",
        section.group("body"),
        re.MULTILINE,
    )
    if value is None:
        raise ValueError(f"{path}: missing {table}.{key}")
    return value.group("value")


# Root plugin.json deliberately carries no version. Anything else in
# JSON_MANIFESTS must have one, so a manifest added later either declares a
# version or is added here on purpose — silence is not an option.
VERSIONLESS_MANIFESTS = frozenset({"plugin.json"})


def json_versions(path: str, root: Path = ROOT) -> dict[str, str | None]:
    """Every version location in a manifest, keyed by where it was found.

    Discovered rather than listed, so a manifest added later is compared
    without anyone remembering to register it. A location that exists but
    carries no version maps to ``None``: every marketplace entry is its own
    location, so one entry losing its version cannot hide behind a sibling
    that still has one.
    """
    data = load_json(path, root)
    found: dict[str, str | None] = {}
    version = data.get("version")
    if version is not None:
        found[path] = str(version)
    plugins = data.get("plugins") or []
    if isinstance(plugins, list):
        for index, plugin in enumerate(plugins):
            if isinstance(plugin, dict):
                entry = plugin.get("version")
                found[f"{path}#plugins[{index}]"] = (
                    None if entry is None else str(entry)
                )
    return found


def changelog_version(root: Path = ROOT) -> tuple[str | None, str]:
    """The version token of the *newest* `## ` heading, and that heading's text.

    Deliberately not a search for the first semver-shaped heading anywhere: a
    malformed newest heading (`## 0.3 (unreleased)`) would then be skipped in
    favour of an older one that happens to match the canonical version, and the
    drift would pass unnoticed.
    """
    for line in (root / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            match = re.match(rf"(?P<version>{VERSION_PATTERN})(?=\s|$)", heading)
            return (match.group("version") if match else None), heading
    return None, ""


def validate_versions(root: Path = ROOT) -> list[str]:
    expected = toml_string(".ai-rulez/config.toml", "plugin", "version", root)
    errors: list[str] = []
    actual: dict[str, str] = {}

    for manifest in JSON_MANIFESTS:
        try:
            found = json_versions(manifest, root)
        except (OSError, json.JSONDecodeError):
            # collect_manifest_errors() already reports unreadable manifests;
            # raising here would replace its diagnostic with a traceback.
            continue
        if not found and manifest not in VERSIONLESS_MANIFESTS:
            errors.append(f"{manifest}: no version field found")
        for where, value in found.items():
            if value is None:
                errors.append(f"{where}: no version field found")
            else:
                actual[where] = value

    version, heading = changelog_version(root)
    if version is None:
        errors.append(
            f"CHANGELOG.md: newest heading {heading!r} does not start with a version"
        )
    else:
        actual["CHANGELOG.md"] = version

    errors += [
        f"{path}: version {value!r} != {expected!r}"
        for path, value in actual.items()
        if value != expected
    ]
    return errors


#: Keys the manifest is allowed to declare at column zero. Anything else there is a
#: block scalar that lost its indentation, which silently changes what the document
#: means -- see validate_manifest_shape.
MANIFEST_TOP_LEVEL_KEYS = ("org", "domain", "hcp_api", "preflight", "steps")


#: The credential terraform itself prefers. Every place the shipped guidance
#: derives HCP_TOKEN has to follow the same order, or a repo using the
#: environment route gets an empty bearer token -- or worse, a stale
#: apply-capable one from a file that should no longer matter.
TOKEN_FILE_DERIVATION = "HCP_TOKEN=$(jq"


def validate_token_resolution(root: Path = ROOT) -> list[str]:
    """No shipped source may derive HCP_TOKEN from the credentials file alone.

    Nine documents did, found separately across four review rounds: Step 0,
    docs/state.md, hcp-verify, then hcp.md twice, cloudflare.md, github.md,
    docs/hcp-api.md, the manifest's own comment, and finally docs/policy.md --
    which the first version of this validator missed because it scanned only
    .ai-rulez/skills. Hand-authored guidance ships too: an operator following a
    snippet in docs/ replaces a plan-only token just as effectively.
    """
    roots = (root / ".ai-rulez/skills", root / "docs")
    return [
        f"{path.relative_to(root)}:{number}: derives HCP_TOKEN from the "
        "credentials file alone; use ${TF_TOKEN_app_terraform_io:-...} as config.md does"
        for scan_root in roots
        for path in sorted(scan_root.rglob("*"))
        if path.is_file() and path.suffix in {".md", ".yaml", ".sh"}
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        )
        if TOKEN_FILE_DERIVATION in line.replace(" ", "")
        and "TF_TOKEN_app_terraform_io" not in line
    ]


def validate_manifest_shape(root: Path = ROOT) -> list[str]:
    """Reject a column-zero line the manifest does not permit there.

    Nothing in this repository parses steps.yaml as YAML: ai-rulez copies it
    verbatim and the tests read it as text, so a broken document passed every
    check. A `run: |` paragraph that lost its leading spaces terminated the
    scalar and left a bare token at the document root -- the authoritative phase
    manifest stopped parsing and `make check` stayed green.

    This is a shape check, not a parser. It catches the class that actually
    happens when editing this file: content escaping a block scalar. Adding a
    real YAML parser would mean a new runtime dependency for one file.
    """
    errors: list[str] = []
    for relative in (
        ".ai-rulez/skills/infra-copilot/references/steps.yaml",
        "skills/infra-copilot/references/steps.yaml",
    ):
        text = read_document(root / relative)
        if text is None:
            errors.append(f"{relative}: unreadable, cannot check manifest shape")
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if not line or line[:1].isspace() or line.startswith("#"):
                continue
            key = line.split(":", 1)[0]
            if key in MANIFEST_TOP_LEVEL_KEYS:
                continue
            errors.append(
                f"{relative}:{number}: {line.strip()[:60]!r} starts at column 0 but is "
                "not a top-level key; a block scalar has lost its indentation"
            )
    return errors


#: The `infra-auditor` manifest, and how each host's row in hosts.md spells its
#: `tools` field. Only the shape lives here -- the path, the dialect and the tool
#: names come from the table, so it stays authoritative rather than descriptive.
#: Columns each capability section must declare. A mistyped header built rows
#: under an unexpected key and every later lookup raised KeyError, ending the run
#: with a traceback instead of naming the malformed record.
REQUIRED_HEADERS = {
    "## Subagent manifests": {
        "Host", "Discovery path", "`tools` dialect", "Tool names",
        "Invocation tool", "Shipped",
    },
    "## Hook discovery": {"Host", "Manifest path", "Matcher", "Root variable", "Shipped"},
}
#: The one command allowed to delegate, whose grant must carry the recorded
#: invocation tool -- and the host that grant belongs to.
#:
#: `commands/*.md` with an `allowed-tools` line is Claude's adapter format;
#: hosts.md records that Codex exposes no plugin slash commands at all and that
#: OpenCode loads skills through its own tool. So there is no `allowed-tools`
#: anywhere to check another host's invocation tool against, and the cross-check
#: applies to the row whose adapter this actually is.
STATUS_COMMAND = "infra-status.md"
STATUS_COMMAND_HOST = "Claude Code"
AGENT_STEM = "infra-auditor"
#: How each dialect spells a whole frontmatter block, given the tool names its
#: row records. `{description}` is the only free value.
#:
#: Rendered and compared rather than validated field by field. The previous
#: version checked properties -- allowed keys, no duplicates, balanced quotes,
#: valid escapes, escape payload widths, indentation, scalar shape -- and each
#: rule left an adjacent malformation to probe, because YAML is larger than any
#: list of rules about it. A rendered block answers all of them at once: an
#: unknown key, a doubled quote, an invalid escape and an indented mapping all
#: fail as "not equal" without a rule apiece, and no YAML parser is needed to say
#: so.
AGENT_FRONTMATTER = {
    "comma string": (
        ".md",
        "name: {name}\ndescription: \"{description}\"\ntools: {tools}",
        lambda names: ", ".join(names),
    ),
    "YAML list": (
        ".md",
        "name: {name}\ndescription: \"{description}\"\ntools:\n{tools}",
        lambda names: "\n".join(f"  - {name}" for name in names),
    ),
    "bool map": (
        ".md",
        "name: {name}\ndescription: \"{description}\"\nmode: subagent\ntools:\n{tools}",
        lambda names: "\n".join(f"  {name}: true" for name in names),
    ),
    # TOML, parsed with tomllib rather than rendered: its body is prose in a
    # multi-line string, so there is no fixed block to compare against.
    "none": (".toml", None, None),
}
#: A description may not carry a quote or a backslash. That is not a style rule:
#: it removes every escape and quoting question from this document by
#: construction, which is what the escape-validation rules were reaching for.
AGENT_DESCRIPTION = re.compile(r'\A[^"\\\n]+\Z')
AGENT_DIALECTS = {name: (suffix, body) for name, (suffix, body, _) in AGENT_FRONTMATTER.items()}


#: Keyed by dialect, in each host's own spelling. One global Claude-cased pair
#: meant the OpenCode row could never graduate: its native grant is lowercase, so
#: `Skill`/`Bash` were unsatisfiable however the row was written.
#:
#: Antigravity records no skill-loading tool at all, which is a gap in that row
#: rather than something this gate can invent -- it is one of the reasons that row
#: is not shipped.
AGENT_REQUIRED_TOOLS = {
    "comma string": ("Skill", "Bash"),
    "bool map": ("skill", "bash"),
    # No skill-loading tool is recorded for this dialect, and the manifest's first
    # instruction is to load the runbook by name. A row without one cannot ship:
    # every delegated run would fail before reaching the scan. Recorded in
    # hosts.md as one of the reasons that row is unshipped; enforced here so the
    # record cannot be flipped without the missing capability being established.
    "YAML list": None,
    # Session tools are inherited, so the read-only grant the protocol promises
    # cannot be expressed or checked. Unshippable for the same reason the
    # YAML-list dialect is: the record would claim a narrowing that does not exist.
    "none": None,
}
#: Tools that would make the read-only contract unstatable.
#: Keyed by dialect, like AGENT_REQUIRED_TOOLS and for the same reason: one
#: Claude-cased tuple let OpenCode's native lowercase `write` through, handing a
#: read-only auditor a direct write capability behind a green gate.
AGENT_FORBIDDEN_TOOLS = {
    "comma string": ("Write", "Edit", "NotebookEdit"),
    "bool map": ("write", "edit", "patch"),
    "YAML list": ("write_to_file", "replace_file_content", "edit_file"),
    "none": (),
}
#: The agent must delegate to the runbook, and must not carry a repo-relative path
#: to it: its working directory is the *consuming* repository, so
#: "skills/infra-copilot/references/..." resolves into the consumer and finds
#: nothing -- it only looks right from a source checkout of this repository.
AGENT_RUNBOOK = ("infra-copilot", "status.md")
#: A positive directive, not a mention. The imperative and the skill name have to
#: appear together and in that order. Backticks are optional: the TOML dialect
#: carries its body in a plain string, where Markdown code spans do not belong.
#:
#: Case-sensitive on `Invoke` so the sentence has to be an instruction, and the
#: negator guard is what makes it a *positive* one -- "Never Invoke the
#: infra-copilot skill" matched the imperative and inverted it.
AGENT_INVOCATION = re.compile(r"\bInvoke the `?infra-copilot`? skill\b")
#: An instruction to use the runbook, not a sentence that mentions it. "The file
#: status.md exists" named it and told the agent nothing.
AGENT_RUNBOOK_DIRECTIVE = re.compile(
    r"\b(?:follow|run|use|read|consult)\b[^.]{0,60}?status\.md"
)
#: A negator anywhere in the same clause disqualifies what follows it. Bounded by
#: clause punctuation and a short distance, because the negator and the thing it
#: negates are usually separated by a verb -- "do not *follow* status.md" slipped
#: past a rule that required them adjacent.
AGENT_NEGATOR = re.compile(
    r"\b(?:never|not|nor|avoid|don'?t|cannot|can'?t|refuse)\b[^.;:\n]{0,24}$",
    re.IGNORECASE,
)
#: Any relative path to the runbook, not one spelling. The agent's working
#: directory is the consuming repository, so `references/status.md` resolves
#: there just as `skills/infra-copilot/references/status.md` does.
AGENT_FORBIDDEN_PATH = re.compile(r"(?<![\w/])[\w.-]+(?:/[\w.-]+)*/status\.md")
#: An adapter budget, in the spirit of MAX_DESCRIPTION_BUDGET: the runbook owns
#: scope, guardrails and the report contract, and a manifest with room to restate
#: them will.
AGENT_MAX_LINES = 40
#: And a character budget, because `agents/` is outside the Markdown line-length
#: lint: thousands of words on one physical line kept the line count green while
#: making the manifest exactly the second authority the budget exists to prevent.
AGENT_MAX_CHARACTERS = 2600
#: The one shell script every hook manifest must hand to a shell. Adapters carry
#: the discovery path and the matcher; the behaviour is shared.
HOOK_IMPLEMENTATION = "hooks/session-start.sh"
#: The one command every host's SessionStart callback runs, as a template over
#: the root variable that host's row records.
#:
#: Compared byte-for-byte rather than analysed. The previous version modelled
#: POSIX shell -- assignments, guards, terminals, expansions, redirections -- to
#: decide whether a command "ran the implementation", and every tightening left
#: an adjacent spelling to probe: `echo sh <path>`, `sh -c true`, a reassigned
#: variable, `exec`, `false || exit`, `&& exit`, `[ ! -f ]`, `[ -z ]`, `%/*`,
#: `>/dev/null`, a trailing `touch`. Twenty-two spellings, each finding correct,
#: none of them a manifest anyone would write.
#:
#: The input here is closed: four hand-authored adapters, one line each, derived
#: from a record this file already owns. For a closed set, rendering the expected
#: value and comparing is both shorter and complete -- every one of those
#: spellings fails as "not equal" without a rule of its own. It is the same
#: choice COMMAND_TOOLS already makes for `allowed-tools`.
#:
#: The cost is deliberate: changing the command means changing the record in the
#: same commit, which is the coupling this table exists to enforce.
HOOK_COMMAND_TEMPLATE = (
    'r="${{{root}:-}}"; [ -n "$r" ] || exit 0; '
    's="${{r%/}}/hooks/session-start.sh"; [ -f "$s" ] || exit 0; sh "$s"'
)
#: hosts.md writes a literal "|" in a matcher as {pipe}: a Markdown cell cannot
#: carry one, and escaping it would put the escape into a value compared
#: byte-for-byte against the shipped manifest.
MATCHER_PIPE = "{pipe}"
#: The rest of the callback, which is identical on every host.
HOOK_TIMEOUT = 10
HOOK_DESCRIPTION = 'Announce that infra-copilot is installed when the working directory looks like a managed infra repo.'


def _output_branch(script: str) -> str | None:
    """The host-output conditional of session-start.sh, or None when absent.

    Scoped rather than searched: a comment naming a variable satisfied a
    whole-file test while the branch that decides the output shape never tested
    it, so the hook ran and emitted the fallback shape. Naming is not testing --
    the same distinction the callback check already draws between a command that
    mentions the implementation and one that runs it.
    """
    start = script.find('if [ -n "$')
    if start < 0:
        return None
    end = script.find("; then", start)
    return None if end < 0 else script[start:end]


def expected_hook_command(root_variable: str) -> str:
    """The callback command a host's manifest must carry, verbatim."""
    return HOOK_COMMAND_TEMPLATE.format(root=root_variable)


def dialect_headers(root: Path = ROOT, heading: str = "") -> list[str]:
    """The column headers of the hosts.md table under ``heading``, in order.

    A list, not a set: a repeated name passed a set comparison and then had
    ``dict(zip(...))`` silently keep the later column, so the value a reader sees
    under `Shipped` and the one every rule read were different cells.
    """
    for line in _section_lines(root, heading):
        return [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip("|"))]
    return []


def _section_lines(root: Path, heading: str) -> list[str]:
    """Table lines of the section under ``heading``, header first."""
    text = read_document(root / HOSTS_DOCUMENT)
    if text is None or text.count(heading) != 1:
        return []
    section = text[text.index(heading) + len(heading) :]
    cut = section.find("\n## ")
    return [
        line.strip()
        for line in (section if cut < 0 else section[:cut]).splitlines()
        if line.strip().startswith("|") and not set(line.strip()) <= set("|-: ")
    ]


def dialect_rows(root: Path = ROOT, heading: str = "") -> list[dict[str, str]]:
    """Body rows of the hosts.md table under ``heading``, keyed by column header.

    Keyed rather than positional, and exact-width: a row carrying an extra cell
    made `row[-1]` a different column from the one a reader sees under `Shipped`,
    so the gate and the document disagreed about the same host. A row whose width
    does not match the header is returned with a `_defect` key instead of being
    guessed at.
    """
    text = read_document(root / HOSTS_DOCUMENT)
    if text is None or text.count(heading) != 1:
        return []
    section = text[text.index(heading) + len(heading) :]
    cut = section.find("\n## ")
    headers: list[str] = []
    rows: list[dict[str, str]] = []
    for line in (section if cut < 0 else section[:cut]).splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or set(stripped) <= set("|-: "):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped.strip("|"))]
        if not headers:
            headers = cells
            continue
        if len(cells) != len(headers):
            rows.append({
                "Host": cells[0] if cells else "",
                "_defect": f"has {len(cells)} cells, not {len(headers)}",
            })
            continue
        rows.append(dict(zip(headers, cells)))
    return rows


def _canonical(relative: str) -> str:
    """A recorded path reduced to one spelling, so equivalents compare equal."""
    return posixpath.normpath(relative.rstrip("/") or ".")


def _escapes_root(root: Path, relative: str) -> str | None:
    """Why a recorded path leaves the plugin payload, or None when it stays inside.

    Resolved, not just lexical: a lexically clean path can still be a symlink out
    of the tree, and the payload root is what an installed plugin joins against.
    """
    if relative.startswith(("/", "~")) or PurePosixPath(relative).is_absolute():
        return "is absolute"
    try:
        (root / relative).resolve().relative_to(root.resolve())
    except ValueError:
        return "escapes the plugin root"
    return None


def _shipped(cell: str) -> bool:
    """Whether a Shipped cell is the table's exact affirmative.

    Exact, not a prefix: `yes — withdrawn` read as shipped, so a typo or a
    trailing comment could turn a refusal into a capability claim. Anything that
    is not exactly "yes" is a refusal here, and `_malformed_shipped` reports the
    values that are neither.
    """
    return cell.strip("* ").strip().lower() == "yes"


def _malformed_shipped(cell: str) -> bool:
    """A Shipped cell that states neither the affirmative nor a refusal."""
    normalised = cell.strip("* ").strip().lower()
    return normalised != "yes" and not normalised.startswith("no")


def validate_host_dialects(root: Path = ROOT) -> list[str]:
    """Hold the shipped agent and hook manifests to hosts.md.

    hosts.md invites these sections and says validate.py gates what it can. What
    it can gate is that a row marked shipped has its artifact in that host's
    dialect, and that a row marked unshipped has no artifact at all -- wiring that
    ships on a guess is indistinguishable from wiring that works, right up until
    someone needs it.
    """
    errors: list[str] = []
    agents = dialect_rows(root, "## Subagent manifests")
    hooks = dialect_rows(root, "## Hook discovery")
    for heading, required in REQUIRED_HEADERS.items():
        headers = dialect_headers(root, heading)
        if not headers:
            continue
        if len(headers) != len(set(headers)):
            repeated = sorted({h for h in headers if headers.count(h) > 1})
            return [
                f"{HOSTS_DOCUMENT}: {heading!r} repeats the column(s) {repeated}; a row's "
                "value would be taken from the later cell, not the one a reader sees"
            ]
        if set(headers) != required:
            return [
                f"{HOSTS_DOCUMENT}: {heading!r} declares columns {sorted(headers)}, "
                f"not {sorted(required)}; every rule reads rows by header name"
            ]
    for relative in PROTOCOL_DOCUMENTS:
        protocol = read_document(root / relative)
        if protocol is None or protocol.count(DELEGATION_HEADING) != 1:
            # Exactly one: the agent reads the whole document, so a second copy
            # could contradict the first while only the first was validated.
            errors.append(
                f"{relative}: {DELEGATION_HEADING!r} occurs "
                f"{0 if protocol is None else protocol.count(DELEGATION_HEADING)} times; "
                "exactly one is required"
            )
            continue
        section = protocol[protocol.index(DELEGATION_HEADING) + len(DELEGATION_HEADING) :]
        cut = section.find("\n### ")
        section = section if cut < 0 else section[:cut]
        for marker in DELEGATION_MARKERS:
            # Affirmative, not present: "never declared or allowed" and "never run
            # the scan inline anywhere" contain every noun and invert the rule.
            # The gate is one phrase: requiring `declared` alone let "declared
            # but denied" satisfy it, which inverts the rule it gates.
            if not _positive_mentions(section, marker if "\\s" in marker else re.escape(marker)):
                errors.append(
                    f"{relative}: the delegation rule is missing {marker!r}; it must "
                    "gate on the recorded row AND on the tool being available, and "
                    "name the inline fallback"
                )
    document = read_document(root / HOSTS_DOCUMENT) or ""
    for heading in ("## Subagent manifests", "## Hook discovery"):
        if document.count(heading) != 1:
            errors.append(
                f"{HOSTS_DOCUMENT}: {heading!r} occurs {document.count(heading)} times; "
                "exactly one is required, or a reader sees competing capability records "
                "and only the first is checked"
            )
    if errors:
        return errors
    if not agents or not hooks:
        return [f"{HOSTS_DOCUMENT}: no subagent or hook rows found; the record is unreadable"]
    # Shape first: a row the reader and the gate would read differently cannot be
    # judged, so it is reported rather than guessed at.
    for label, rows in (("subagent", agents), ("hook", hooks)):
        for row in rows:
            if "_defect" in row:
                errors.append(
                    f"{HOSTS_DOCUMENT}: {label} row {row['Host']!r} {row['_defect']}"
                )
            elif _malformed_shipped(row["Shipped"]):
                errors.append(
                    f"{HOSTS_DOCUMENT}: {row['Host']}'s {label} Shipped cell is "
                    f"{row['Shipped']!r}, which states neither 'yes' nor a refusal"
                )
    if errors:
        return errors
    # The protocol sends a run to *its own* host's row, so a section missing a host
    # leaves that run with no delegation or hook decision at all. The question-tool
    # table is the authoritative host set; both sections must match it exactly.
    expected = set(host_records(root))
    for label, rows in (("subagent", agents), ("hook", hooks)):
        present = [row["Host"] for row in rows]
        if len(present) != len(set(present)):
            errors.append(f"{HOSTS_DOCUMENT}: the {label} section repeats a host row")
        if set(present) != expected:
            errors.append(
                f"{HOSTS_DOCUMENT}: the {label} section covers {sorted(set(present))}, "
                f"not the recorded hosts {sorted(expected)}"
            )
    if errors:
        return errors

    owners = [row for row in agents if _shipped(row["Shipped"])]
    owned: dict[str, list[str]] = {}
    for row in owners:
        owned.setdefault(
            _canonical(row["Discovery path"].strip("`")), []
        ).append(row["Host"])
    for directory, sharing in sorted(owned.items()):
        if len(sharing) > 1:
            errors.append(
                f"{HOSTS_DOCUMENT}: {sharing} all mark {directory!r} shipped; one "
                "directory cannot hold incompatible tools dialects, so only one may"
            )
    for row in agents:
        directory = row["Discovery path"].strip("`")
        if problem := _escapes_root(root, directory):
            errors.append(
                f"{HOSTS_DOCUMENT}: subagent path {directory!r} {problem}; an installed "
                "plugin resolves it against its own payload and finds nothing"
            )
            continue
        dialect = next(
            (k for k in AGENT_DIALECTS if row["`tools` dialect"].startswith(k)), None
        )
        if dialect is None:
            errors.append(
                f"{HOSTS_DOCUMENT}: {row['Host']} declares an unknown tools dialect"
            )
            continue
        suffix, render = AGENT_DIALECTS[dialect]
        relative = f"{directory.rstrip('/')}/{AGENT_STEM}{suffix}"
        text = read_document(root / relative)
        if not _shipped(row["Shipped"]):
            if _canonical(directory) in owned:
                continue
            for stray in sorted((root / directory).glob("*")):
                if stray.is_file():
                    errors.append(
                        f"{directory.rstrip('/')}/{stray.name}: {row['Host']}'s row is "
                        "not marked shipped, so this manifest asserts wiring nothing "
                        "has demonstrated"
                    )
            continue
        if AGENT_REQUIRED_TOOLS.get(dialect, ()) is None:
            # Checked here rather than in _check_agent: the TOML branch returns
            # before that point, so the dialect least able to express the grant
            # was the one never asked about it.
            errors.append(
                f"{HOSTS_DOCUMENT}: the {dialect!r} dialect cannot express the grant the "
                "protocol promises -- no recorded skill-loading tool, or tools inherited "
                "from the session -- so this row cannot be marked shipped until the host "
                "can enforce and record a restricted grant"
            )
        invocation = row["Invocation tool"].strip("` ")
        if invocation not in {"not recorded", "—", ""} and row["Host"] == STATUS_COMMAND_HOST:
            # The command that delegates has to be granted the tool this row
            # names. Renaming the capability here while `allowed-tools` still
            # lists the old one leaves /infra-status silently falling back.
            granted = [
                tool.strip() for tool in COMMAND_TOOLS[STATUS_COMMAND].split(",")
            ]
            if invocation not in granted:
                errors.append(
                    f"{HOSTS_DOCUMENT}: {row['Host']} records {invocation!r} as its "
                    f"invocation tool, but {STATUS_COMMAND} grants {granted}; the "
                    "delegation the protocol describes would not be permitted"
                )
        if invocation in {"not recorded", "—", ""}:
            # The delegation rule gates on this tool being declared and allowed, so a
            # shipped row without one leaves that gate nothing to evaluate.
            errors.append(
                f"{HOSTS_DOCUMENT}: {row['Host']}'s subagent row is shipped but records "
                "no invocation tool; the availability gate would have nothing to check"
            )
        if text is None:
            errors.append(
                f"{relative}: {row['Host']} is marked shipped but no manifest is here"
            )
            continue
        for stray in sorted((root / directory).glob("*")):
            if stray.is_file() and stray.name != f"{AGENT_STEM}{suffix}":
                errors.append(
                    f"{directory.rstrip('/')}/{stray.name}: no subagent row records this "
                    f"manifest, and {row['Host']} discovers every file in {directory!r}"
                )
        errors.extend(_check_agent(relative, text, row, render, dialect))

    for row in hooks:
        relative = row["Manifest path"].strip("`").split("`")[0].split(" ")[0].strip()
        if relative not in {"none", "—", ""} and (
            problem := _escapes_root(root, relative)
        ):
            errors.append(
                f"{HOSTS_DOCUMENT}: hook path {relative!r} {problem}; the validator "
                "would read and accept an artifact no installed plugin can reach"
            )
            continue
        if not _shipped(row["Shipped"]):
            if relative not in {"none", "—", ""} and (root / relative).exists():
                errors.append(
                    f"{relative}: {row['Host']}'s row is not marked shipped, so this "
                    "manifest asserts a discovery path nothing has demonstrated"
                )
            continue
        errors.extend(_check_hook(root, relative, row))
    return errors


def _check_agent(relative: str, text: str, row: dict[str, str], render, dialect: str) -> list[str]:
    """Hold a shipped agent manifest to what its row implies.

    The frontmatter is rendered from the record and compared as a block; the body
    keeps its directive rules, because prose is not derivable.
    """
    errors: list[str] = []
    if dialect == "none":
        # TOML: the body lives in a multi-line string, so there is no fixed block
        # to compare. tomllib is stdlib, so this one is genuinely parsed.
        try:
            document = tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            return [f"{relative}: is not valid TOML ({error})"]
        if document.get("name") != AGENT_STEM:
            errors.append(
                f"{relative}: declares name {document.get('name')!r}, not {AGENT_STEM!r}"
            )
        instructions = document.get("developer_instructions")
        if not isinstance(instructions, str):
            return errors + [
                f"{relative}: declares no `developer_instructions` string; that field "
                "is the agent's body, and the directives have to live in it"
            ]
        return errors + _check_agent_body(relative, instructions)

    front = SKILL_FRONTMATTER.match(text)
    if front is None:
        return [f"{relative}: has no frontmatter block"]
    body = front.group("body")
    description = re.search(r'(?m)^description:\s*"([^"]*)"\s*$', body)
    if description is None or not AGENT_DESCRIPTION.fullmatch(description.group(1)):
        return [
            f"{relative}: needs a `description:` on one line, double-quoted, carrying "
            "no quote or backslash of its own"
        ]
    names = re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", row["Tool names"])
    _, template, render_tools = AGENT_FRONTMATTER[dialect]
    expected = template.format(
        name=AGENT_STEM, description=description.group(1), tools=render_tools(names)
    )
    if body.strip("\n") != expected:
        # One comparison in place of the field-by-field rules: an unknown or
        # duplicated key, a doubled quote, an invalid escape, an indented mapping,
        # a wrong dialect or a renamed agent all differ from this block.
        return [
            f"{relative}: frontmatter does not match what {HOSTS_DOCUMENT} records for "
            f"{row['Host']}. Expected:\n{expected}\nFound:\n{body.strip(chr(10))}"
        ]
    for required in AGENT_REQUIRED_TOOLS.get(dialect) or ():
        if required not in names:
            errors.append(
                f"{HOSTS_DOCUMENT}: the shipped subagent row omits {required!r}; the "
                "manifest loads the runbook through the skill tool and runs shell "
                "checks, so a delegated run would fail"
            )
    for forbidden in AGENT_FORBIDDEN_TOOLS.get(dialect, ()):
        if forbidden in names:
            errors.append(
                f"{HOSTS_DOCUMENT}: the shipped subagent row grants {forbidden!r}; the "
                "scan is read-only and the recorded grant is what says so"
            )
    return errors + _check_agent_body(relative, text)


#: The delegation rule's shape. Both gates have to be stated, because a record
#: says the agent was *shipped*, never that this session can reach it -- and the
#: inline fallback is what makes a denied tool a fallback rather than an error.
DELEGATION_HEADING = "### Running the scan in an isolated context"
DELEGATION_MARKERS = (
    "infra-auditor", r"marked\s+shipped", r"declared\s+and\s+allowed",
    "Invocation tool", "inline",
    # The scope boundary is load-bearing: an action skill's resume scan needs the
    # current-checkout checks the status runbook substitutes away.
    r"`status`\s+and\s+only\s+`status`", r"`setup`,\s+`import`,\s+and\s+`add`",
)


def _positive_mentions(text: str, pattern: str) -> bool:
    """Whether ``pattern`` occurs at least once without a negator before it."""
    return any(
        AGENT_NEGATOR.search(text[max(0, match.start() - 40) : match.start()]) is None
        for match in re.finditer(pattern, text)
    )


def _check_agent_body(relative: str, text: str) -> list[str]:
    """Rules every dialect shares: delegate, no consumer-relative path, stay small.

    The directives are looked for in the *body* only. Frontmatter is discovery
    metadata -- a description tells a caller when to reach for the agent and is
    not what the agent is given as instructions -- so a manifest whose directives
    live there and whose body says "Do nothing." satisfied the contract while
    instructing nothing.
    """
    errors: list[str] = []
    front = SKILL_FRONTMATTER.match(text)
    text = text[front.end() :] if front else text
    if not _positive_mentions(text, AGENT_INVOCATION.pattern):
        # Names alone were satisfied by "Never invoke `infra-copilot` or
        # `status.md`" -- both markers present, every delegated run told not to
        # load the canonical workflow.
        errors.append(
            f"{relative}: carries no instruction to invoke the {AGENT_RUNBOOK[0]!r} "
            "skill; an agent that does not load the runbook either restates it or "
            "does nothing"
        )
    if not _positive_mentions(text, AGENT_RUNBOOK_DIRECTIVE.pattern):
        # "then do not follow status.md" named the runbook and skipped it, which
        # is the same defect as the negated skill imperative one clause earlier.
        errors.append(
            f"{relative}: carries no un-negated instruction to follow "
            f"{AGENT_RUNBOOK[1]!r}; naming the runbook is not delegating to it"
        )
    if found := AGENT_FORBIDDEN_PATH.search(text):
        errors.append(
            f"{relative}: carries the relative runbook path {found.group(0)!r}, which "
            "resolves into the consuming repository rather than the plugin payload; "
            "load the skill by name instead"
        )
    if len(text) > AGENT_MAX_CHARACTERS:
        errors.append(
            f"{relative}: {len(text)} characters > {AGENT_MAX_CHARACTERS}; the line "
            "budget alone is not a size budget when one line may be any length"
        )
    if len(text.splitlines()) > AGENT_MAX_LINES:
        errors.append(
            f"{relative}: {len(text.splitlines())} lines > {AGENT_MAX_LINES}; a host "
            "manifest is an adapter, and one long enough to restate the runbook's scope, "
            "guardrails or report contract becomes a second authority"
        )
    return errors


def _check_hook(root: Path, relative: str, row: dict[str, str]) -> list[str]:
    """Hold a shipped hook manifest to the shape and command its row records.

    The manifest is a fixed shape -- one event, one entry, one callback -- so it
    is compared against a rendered expectation rather than inspected property by
    property. The command in particular is byte-for-byte: see
    HOOK_COMMAND_TEMPLATE for why analysing it was the wrong tool.
    """
    if not (root / relative).exists():
        return [f"{relative}: {row['Host']} is marked shipped but no manifest is here"]
    try:
        payload = load_json(relative, root)
    except (OSError, json.JSONDecodeError) as error:
        return [f"{relative}: is not readable JSON ({error})"]

    recorded_root = row["Root variable"].strip("` ")
    matcher = row["Matcher"].strip("`").replace(MATCHER_PIPE, "|")
    if recorded_root in {"—", ""}:
        return [f"{HOSTS_DOCUMENT}: {row['Host']} is shipped but records no root variable"]
    # The manifest and the record can agree on a variable the shared script does
    # not test, in which case the hook runs and emits the fallback output shape
    # instead of this host's -- the announcement disappearing on a green gate.
    branch = _output_branch(read_document(root / HOOK_IMPLEMENTATION) or "")
    if branch is None:
        return [f"{HOOK_IMPLEMENTATION}: has no host-output conditional to check"]
    if f'[ -n "${{{recorded_root}:-}}" ]' not in branch:
        return [
            f"{HOOK_IMPLEMENTATION}: its host-output conditional does not test "
            f"${{{recorded_root}:-}}, which {HOSTS_DOCUMENT} records as "
            f"{row['Host']}'s root; the hook would run and emit another host's shape"
        ]

    # The whole manifest, rendered from the record. Every shape question the old
    # version asked one at a time -- sibling events, extra top-level keys,
    # duplicate entries or callbacks, a non-string matcher or command, a foreign
    # root variable, a redirection, an added statement -- is answered by this
    # single comparison, because none of them produce this document.
    expected = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": matcher,
                    "hooks": [
                        {
                            "name": "infra-copilot-session-start",
                            "type": "command",
                            "command": expected_hook_command(recorded_root),
                            "timeout": HOOK_TIMEOUT,
                            "description": HOOK_DESCRIPTION,
                        }
                    ],
                }
            ]
        }
    }
    if payload != expected:
        return [
            f"{relative}: does not match what {HOSTS_DOCUMENT} records for "
            f"{row['Host']}. Expected:\n{json.dumps(expected, indent=2)}\n"
            f"Found:\n{json.dumps(payload, indent=2, default=repr)}"
        ]
    return []


def validate_layout() -> list[str]:
    """Artifacts whose absence no other validator would explain.

    Neither the agent manifest nor any hook manifest is here: validate_host_dialects
    already requires one for whichever host records that artifact `verified: true`,
    at the path that record names. Listing them again pinned the old paths, so
    revoking or relocating either could not be expressed in the table without
    failing `make check` -- and main() short-circuits on layout errors, so the
    capability-aware rule would never have run to say otherwise.

    `hooks/session-start.sh` stays: it is the one implementation every manifest
    runs, not a per-host discovery path the table records.
    """
    required = (
        "Makefile",
        ".markdownlint-cli2.jsonc",
        "AGENTS.md",
        "CONTRIBUTING.md",
        "docs/roadmap.md",
        "docs/policy.md",
        # One page per host in hosts.md. Listed here because the caution in #17 is
        # real: litestar-skills documented a templates/ tree its repository did not
        # contain, because no validator covered prose.
        "docs/install-claude-code.md",
        "docs/install-codex.md",
        "docs/install-antigravity.md",
        "docs/install-opencode.md",
        ".github/renovate.json",
        "package.json",
        "package-lock.json",
        ".github/workflows/check.yml",
        ".github/workflows/release.yml",
        ".github/workflows/upstream.yml",
        "hooks/session-start.sh",
        "scripts/upstream.json",
        "scripts/check_upstream.py",
        ".claude-plugin/marketplace.json",
        ".claude-plugin/plugin.json",
        ".agents/plugins/marketplace.json",
        ".codex-plugin/plugin.json",
        "plugin.json",
        ".ai-rulez/skills/infra-copilot/references/config.md",
        ".ai-rulez/skills/infra-copilot/references/config.md.example",
        ".ai-rulez/skills/infra-copilot/references/decisions.md.example",
        ".ai-rulez/skills/infra-copilot/references/hosts.md",
        ".ai-rulez/skills/infra-copilot/references/protocol.md",
        ".ai-rulez/skills/infra-copilot/references/steps.yaml",
        "skills/infra-copilot/references/config.md",
        "skills/infra-copilot/references/config.md.example",
        "skills/infra-copilot/references/decisions.md.example",
        "skills/infra-copilot/references/hosts.md",
        "skills/infra-copilot/references/protocol.md",
        "skills/infra-copilot/references/steps.yaml",
        "skills/infra-copilot/references/checks/status-check-context.sh",
        ".ai-rulez/skills/infra-copilot/references/checks/status-check-context.sh",
    )
    return [
        f"{path}: required host artifact is missing"
        for path in required
        if not (ROOT / path).exists()
    ]


def main(argv: list[str] | None = None) -> int:
    # `--closure <skill>` prints the install arguments for one skill and its
    # dependencies, so `make smoke-opencode` asserts a real resolved closure instead
    # of a hand-copied skill list that drifts the first time a skill is added.
    arguments = sys.argv[1:] if argv is None else argv
    if arguments:
        if arguments[0] != "--closure" or len(arguments) != 2:
            print("usage: validate.py [--closure <skill>]", file=sys.stderr)
            return 2
        name = arguments[1]
        if not (ROOT / ".ai-rulez/skills" / name / "SKILL.md").exists():
            print(f"--closure: no skill named {name!r}", file=sys.stderr)
            return 2
        if name in ROUTER_SKILLS:
            print(
                f"--closure: {name!r} owns no operations; installed alone it routes to "
                "nothing. Name the action skill you want -- its closure includes the hub.",
                file=sys.stderr,
            )
            return 2
        # Every member, both trees: the closure is derived from .ai-rulez/, but
        # `skills add` consumes the shipped skills/ tree. Checking only the root let
        # a reachable-but-unshipped dependency be printed as an install argument the
        # installer cannot satisfy -- which surfaces as a bare installer error.
        closure = skill_closure(name)
        missing = [
            f"{tree}/{skill}"
            for skill in closure
            for tree in (".ai-rulez/skills", "skills")
            if not (ROOT / tree / skill / "SKILL.md").exists()
        ]
        if missing:
            print(
                f"--closure: {name!r} needs {', '.join(missing)}, which "
                f"{'does' if len(missing) == 1 else 'do'} not exist",
                file=sys.stderr,
            )
            return 2
        print(" ".join(f"--skill {skill}" for skill in closure))
        return 0

    # Layout is a precondition for everything below: every content validator reads
    # files this list asserts exist, and Python builds the whole list before main
    # can print any of it. Without this short-circuit a missing artifact surfaces
    # as a FileNotFoundError traceback from whichever validator happened to touch
    # it first -- hiding the one diagnostic that names the file. Guarding each
    # read would mean 25 guards saying the same thing.
    layout_errors = validate_layout()
    if layout_errors:
        for error in layout_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    errors = [
        *validate_skills(),
        *validate_command_tools(),
        *validate_skill_sections(),
        *validate_description_budget(),
        *validate_config_fallbacks(),
        *validate_customization_markers(),
        *validate_manifest_shape(),
        *validate_host_contract(),
        *validate_host_dialects(),
        *validate_token_resolution(),
        *validate_phase_five_rule(),
        *validate_toolchain_contract(),
        *validate_shipped_check_paths(),
        *collect_manifest_errors(),
        *validate_links(),
        *validate_tool_pins(),
        *validate_versions(),
    ]
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("portable skills, links, and host adapters are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
