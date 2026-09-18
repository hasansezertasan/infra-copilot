#!/usr/bin/env python3
"""Validate portable skill links and host adapter metadata."""

from __future__ import annotations

import json
import re
import sys
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
TOOL_PIN_SPECS = {
    "ai-rulez": "AI_RULEZ_VERSION",
    "skills": "SKILLS_VERSION",
    "markdownlint-cli2": "MARKDOWNLINT_VERSION",
}
# Workflows call `make check` and must not carry their own copy of a pin; a
# second definition is exactly the drift this check exists to prevent.
TOOL_PIN_WORKFLOWS = (
    ".github/workflows/check.yml",
    ".github/workflows/release.yml",
    ".github/workflows/upstream.yml",
)
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
    """The Makefile owns every tool pin; README must document the same versions.

    Previously each workflow carried its own copy of both versions, so the two
    could drift apart silently. The Makefile is now the single definition, and
    the workflows are asserted not to reintroduce one.
    """
    errors: list[str] = []
    makefile = (root / MAKEFILE_PATH).read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    for package, variable in TOOL_PIN_SPECS.items():
        match = re.search(
            rf"^{re.escape(variable)}\s*:?=\s*(?P<version>{VERSION_PATTERN})\s*$",
            makefile,
            re.MULTILINE,
        )
        if match is None:
            errors.append(f"{MAKEFILE_PATH}: missing {variable}")
            continue
        pinned = match.group("version")
        documented = set(
            re.findall(rf"{re.escape(package)}@(?P<version>{VERSION_PATTERN})", readme)
        )
        if not documented:
            errors.append(f"README.md: missing pinned {package} command")
        elif documented != {pinned}:
            details = ", ".join(sorted(documented))
            errors.append(
                f"{package}: README documents {details}, {MAKEFILE_PATH} pins {pinned}"
            )
        for relative in TOOL_PIN_WORKFLOWS:
            try:
                workflow = (root / relative).read_text(encoding="utf-8")
            except OSError as error:
                errors.append(f"{relative}: cannot read workflow: {error}")
                continue
            # Any `<package>@…` reference, not just a literal version. The form
            # this replaced was indirect — `ai-rulez@${INFRA_COPILOT_..._VERSION}`
            # with the value in `env:` — so matching only a literal semver would
            # miss exactly the pattern being removed.
            if re.search(rf"(?<![\w-]){re.escape(package)}@", workflow):
                errors.append(
                    f"{relative}: invokes {package}@… directly; "
                    f"call `make` so {MAKEFILE_PATH} stays the only definition"
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
AGENT_STEM = "infra-auditor"
AGENT_DIALECTS = {
    "comma string": (".md", lambda names: "tools: " + ", ".join(names)),
    "YAML list": (".md", lambda names: "tools:\n" + "\n".join(f"  - {n}" for n in names)),
    "bool map": (".md", lambda names: "tools:\n" + "\n".join(f"  {n}: true" for n in names)),
    "none": (".toml", None),
}
#: hosts.md writes a literal "|" in a matcher as {pipe}: a Markdown cell cannot
#: carry one, and escaping it would put the escape into a value compared
#: byte-for-byte against the shipped manifest.
MATCHER_PIPE = "{pipe}"
#: Tools the shipped manifest's own instructions depend on: it loads the runbook
#: through the skill tool and its scan runs shell checks. Deliberately not derived
#: from the table -- the table records what is granted, this what is needed, and
#: deriving one from the other would only compare the grant with itself.
AGENT_REQUIRED_TOOLS = ("Skill", "Bash")
#: Tools that would make the read-only contract unstatable.
AGENT_FORBIDDEN_TOOLS = ("Write", "Edit", "NotebookEdit", "replace_file_content")
#: The agent must delegate to the runbook, and must not carry a repo-relative path
#: to it: its working directory is the *consuming* repository, so
#: "skills/infra-copilot/references/..." resolves into the consumer and finds
#: nothing -- it only looks right from a source checkout of this repository.
AGENT_RUNBOOK = ("infra-copilot", "status.md")
AGENT_FORBIDDEN_PATH = "skills/infra-copilot/references/"
#: An adapter budget, in the spirit of MAX_DESCRIPTION_BUDGET: the runbook owns
#: scope, guardrails and the report contract, and a manifest with room to restate
#: them will.
AGENT_MAX_LINES = 40
#: The one shell script every hook manifest must hand to a shell. Adapters carry
#: the discovery path and the matcher; the behaviour is shared.
HOOK_IMPLEMENTATION = "hooks/session-start.sh"
#: ponytail: substring + shell-present, not a shell parse. The shipped commands
#: resolve the path into a variable first (`s="${r%/}/hooks/session-start.sh"; sh
#: "$s"`), so the two cannot be required adjacent. This rejects the failure that
#: happens -- a no-op adapter that merely names the path, which `echo <path>`
#: passed -- and not a command contriving to run an unrelated shell beside it.
HOOK_SHELL = re.compile(r"(?:^|[;&|]|\s)(?:ba|z|da)?sh\s")


def dialect_rows(root: Path = ROOT, heading: str = "") -> list[list[str]]:
    """Body rows of the hosts.md table under ``heading``, as stripped cells."""
    text = read_document(root / HOSTS_DOCUMENT)
    if text is None or heading not in text:
        return []
    section = text[text.index(heading) + len(heading) :]
    cut = section.find("\n## ")
    rows = []
    for line in (section if cut < 0 else section[:cut]).splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or set(stripped) <= set("|-: "):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped.strip("|"))]
        if cells and cells[0] not in {"Host"}:
            rows.append(cells)
    return rows


def _shipped(cell: str) -> bool:
    """Whether a Shipped cell says yes. Anything else is a recorded refusal."""
    return cell.strip("* ").lower().startswith("yes")


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
    if not agents or not hooks:
        return [f"{HOSTS_DOCUMENT}: no subagent or hook rows found; the record is unreadable"]

    owners = [row for row in agents if _shipped(row[-1])]
    # Per directory, not globally. Claude and Antigravity collide at root agents/ and
    # only one of them may own it, but .codex/agents/ and .opencode/agents/ are
    # independent -- a global count would make those rows impossible to graduate.
    # Zero shipped rows is also legal: withdrawing the agent is a state the record
    # may express, and the unshipped-path rule then keeps the file from lingering.
    owned: dict[str, list[str]] = {}
    for row in owners:
        owned.setdefault(row[1].strip("`"), []).append(row[0])
    for directory, sharing in sorted(owned.items()):
        if len(sharing) > 1:
            errors.append(
                f"{HOSTS_DOCUMENT}: {sharing} all mark {directory!r} shipped; one "
                "directory cannot hold incompatible tools dialects, so only one may"
            )
    for row in agents:
        if len(row) < 5:
            errors.append(f"{HOSTS_DOCUMENT}: subagent row {row[:1]} is missing columns")
            continue
        directory = row[1].strip("`")
        if ".." in PurePosixPath(directory).parts or directory.startswith(("/", "~")):
            errors.append(
                f"{HOSTS_DOCUMENT}: subagent path {directory!r} escapes the plugin root; an "
                "installed plugin resolves it against its own payload and finds nothing"
            )
            continue
        dialect = next((key for key in AGENT_DIALECTS if row[2].startswith(key)), None)
        if dialect is None:
            errors.append(f"{HOSTS_DOCUMENT}: {row[0]} declares an unknown tools dialect")
            continue
        suffix, render = AGENT_DIALECTS[dialect]
        relative = f"{directory.rstrip('/')}/{AGENT_STEM}{suffix}"
        text = read_document(root / relative)
        if not _shipped(row[-1]):
            # The documented collision: an unshipped row may name the directory the
            # shipped one owns. The owner's dialect check governs that file, and
            # reporting it here would make the collision unshippable rather than recorded.
            if text is not None and directory not in owned:
                errors.append(
                    f"{relative}: {row[0]}'s row is not marked shipped, so this manifest "
                    "asserts wiring nothing has demonstrated"
                )
            continue
        if text is None:
            errors.append(f"{relative}: {row[0]} is marked shipped but no manifest is here")
            continue
        # The host discovers the whole directory, not the one filename this record
        # names. An unrecorded sibling is an agent nobody reviewed, with whatever
        # grant it declares -- `agents/rogue.md` carrying `tools: Write` passed.
        for stray in sorted((root / directory).glob("*")):
            if stray.is_file() and stray.name != f"{AGENT_STEM}{suffix}":
                errors.append(
                    f"{directory.rstrip('/')}/{stray.name}: no subagent row records this "
                    f"manifest, and {row[0]} discovers every file in {directory!r}"
                )
        errors.extend(_check_agent(relative, text, row, render))

    for row in hooks:
        if len(row) < 4:
            errors.append(f"{HOSTS_DOCUMENT}: hook row {row[:1]} is missing columns")
            continue
        relative = row[1].strip("`").split("`")[0].split(" ")[0].strip()
        if not _shipped(row[-1]):
            if relative not in {"none", "—", ""} and (root / relative).exists():
                errors.append(
                    f"{relative}: {row[0]}'s row is not marked shipped, so this manifest "
                    "asserts a discovery path nothing has demonstrated"
                )
            continue
        errors.extend(_check_hook(root, relative, row))
    return errors


def _check_agent(relative: str, text: str, row: list[str], render) -> list[str]:
    errors: list[str] = []
    if render is None:
        # TOML, whose tools are inherited: there is no frontmatter, and the name is
        # a top-level key. Requiring YAML here made the Codex row unable to graduate
        # in the one format its own record describes.
        declared = re.search(r'(?m)^name\s*=\s*"([^"]*)"', text)
        if declared is None or declared.group(1) != AGENT_STEM:
            errors.append(f"{relative}: must declare name {AGENT_STEM!r}")
        return errors + _check_agent_body(relative, text)
    front = SKILL_FRONTMATTER.match(text)
    if front is None:
        return [f"{relative}: no YAML frontmatter to read `tools` and `name` from"]
    body = front.group("body")
    name = re.search(r"(?m)^name:\s*(\S+)", body)
    if name is None or name.group(1).strip("\"'") != AGENT_STEM:
        errors.append(f"{relative}: must declare name {AGENT_STEM!r}; the protocol delegates to it")
    if render is not None:
        names = re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", row[3])
        declared = re.findall(r"^tools:.*?(?=^\S|\Z)", body + "\n", re.MULTILINE | re.DOTALL)
        if len(declared) != 1:
            errors.append(
                f"{relative}: frontmatter declares {len(declared)} `tools` fields; exactly "
                "one is required for the grant to be unambiguous"
            )
        elif names and declared[0].strip() != render(names):
            errors.append(
                f"{relative}: frontmatter tools {declared[0].strip()!r} != {render(names)!r} "
                f"as {HOSTS_DOCUMENT} records it; a wrong dialect fails silently"
            )
        for required in AGENT_REQUIRED_TOOLS:
            if required not in names:
                errors.append(
                    f"{HOSTS_DOCUMENT}: the shipped subagent row omits {required!r}; the "
                    "manifest loads the runbook through the skill tool and runs shell "
                    "checks, so a delegated run would fail"
                )
        for forbidden in AGENT_FORBIDDEN_TOOLS:
            if forbidden in names:
                errors.append(
                    f"{HOSTS_DOCUMENT}: the shipped subagent row grants {forbidden!r}; the "
                    "scan is read-only and the recorded grant is what says so"
                )
    return errors + _check_agent_body(relative, text)


def _check_agent_body(relative: str, text: str) -> list[str]:
    """Rules every dialect shares: delegate, no consumer-relative path, stay small."""
    errors: list[str] = []
    for marker in AGENT_RUNBOOK:
        if marker not in text:
            errors.append(
                f"{relative}: must delegate to the {marker!r} runbook; an agent that "
                "restates the scan becomes a second behavioural authority"
            )
    if AGENT_FORBIDDEN_PATH in text:
        errors.append(
            f"{relative}: carries the repo-relative path {AGENT_FORBIDDEN_PATH!r}, which "
            "resolves into the consuming repository rather than the plugin payload"
        )
    if len(text.splitlines()) > AGENT_MAX_LINES:
        errors.append(
            f"{relative}: {len(text.splitlines())} lines > {AGENT_MAX_LINES}; a host "
            "manifest is an adapter, and one long enough to restate the runbook's scope, "
            "guardrails or report contract becomes a second authority"
        )
    return errors


def _check_hook(root: Path, relative: str, row: list[str]) -> list[str]:
    errors: list[str] = []
    if not (root / relative).exists():
        return [f"{relative}: {row[0]} is marked shipped but no manifest is here"]
    try:
        payload = load_json(relative, root)
        entries = payload["hooks"]["SessionStart"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        return [f"{relative}: no SessionStart hooks entry to check ({error})"]
    if set(payload.get("hooks", {})) != {"SessionStart"}:
        errors.append(
            f"{relative}: declares hook events {sorted(payload.get('hooks', {}))}; only "
            "SessionStart is recorded, and a sibling such as PreToolUse would run "
            "behaviour no capability record authorises"
        )
    if set(payload) != {"hooks"}:
        errors.append(
            f"{relative}: top-level keys {sorted(payload)} != ['hooks']; a manifest takes "
            "no siblings of 'hooks' -- Antigravity counts each one as a hook"
        )
    recorded = row[2].strip("`").replace(MATCHER_PIPE, "|")
    actual = {str(entry.get("matcher")) for entry in entries if isinstance(entry, dict)}
    if actual != {recorded}:
        errors.append(
            f"{relative}: SessionStart matcher {sorted(actual)} != {recorded!r} as "
            f"{HOSTS_DOCUMENT} records it for {row[0]}"
        )
    for entry in entries:
        commands = [
            callback.get("command", "")
            for callback in (entry.get("hooks") if isinstance(entry, dict) else None) or []
            if isinstance(callback, dict)
        ]
        if not commands:
            errors.append(f"{relative}: a SessionStart entry declares no hooks to run")
        elif not all(
            HOOK_IMPLEMENTATION in command and HOOK_SHELL.search(command)
            for command in commands
        ):
            errors.append(
                f"{relative}: a SessionStart command does not hand {HOOK_IMPLEMENTATION} "
                "to a shell; naming the path is not running it"
            )
    return errors


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
