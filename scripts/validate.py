#!/usr/bin/env python3
"""Validate portable skill links and host adapter metadata."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRECTORIES = {".git", "node_modules"}
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
SKILL_FRONTMATTER = re.compile(
    r"\A---\s*\n(?P<body>.*?)\n---\s*\n", re.DOTALL
)
COMMAND_TOOLS = {
    "infra-add.md": "Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion",
    "infra-import.md": "Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion",
    "infra-setup.md": "Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion",
    "infra-status.md": "Read, Bash, Glob, Grep",
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
PHASE_FIVE_RULE_DOCUMENT = ".ai-rulez/skills/status/SKILL.md"
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
TOOLCHAIN_SETUP_DOCUMENT = ".ai-rulez/skills/infra-copilot/references/docs/setup.md"
TOOLCHAIN_IMPORT_DOCUMENT = ".ai-rulez/skills/infra-copilot/references/docs/import.md"
TOOLCHAIN_CONFIG_DOCUMENT = ".ai-rulez/skills/infra-copilot/references/config.md"
TOOLCHAIN_STATUS_DOCUMENT = ".ai-rulez/skills/status/SKILL.md"
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
        'MISE_LOCKED=1 mise install --dry-run "$tool"',
    ):
        if marker not in steps:
            errors.append(f"{TOOLCHAIN_STEPS_DOCUMENT}: missing {marker!r}")
    if re.search(r"mise install[^\n]*\$pinned", steps):
        errors.append(
            f"{TOOLCHAIN_STEPS_DOCUMENT}: newline-delimited tool pins rely on "
            "shell-specific word splitting"
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

    if hcp.count('"terraform-version"') < 3 or "set_tf_version" not in hcp:
        errors.append(
            f"{TOOLCHAIN_HCP_DOCUMENT}: Terraform pin must be created, reconciled, "
            "and verified"
        )
    for document, document_name in (
        (steps, TOOLCHAIN_STEPS_DOCUMENT),
        (hcp, TOOLCHAIN_HCP_DOCUMENT),
    ):
        if (
            document.count(
                'index(".infra-copilot/config.md") != null'
            )
            < 1
        ):
            errors.append(
                f"{document_name}: every HCP workspace must watch the shared config"
            )
    if '"trigger-patterns":[$dir+"/**", ".infra-copilot/config.md"]' not in hcp:
        errors.append(
            f"{TOOLCHAIN_HCP_DOCUMENT}: workspace creation must include the shared "
            "config trigger"
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


def validate_layout() -> list[str]:
    required = (
        "Makefile",
        ".markdownlint-cli2.jsonc",
        "AGENTS.md",
        "CONTRIBUTING.md",
        "docs/roadmap.md",
        ".github/renovate.json",
        ".github/workflows/check.yml",
        ".github/workflows/release.yml",
        ".github/workflows/upstream.yml",
        "hooks/session-start.sh",
        "hooks/hooks.json",
        "scripts/upstream.json",
        "scripts/check_upstream.py",
        ".claude-plugin/marketplace.json",
        ".claude-plugin/plugin.json",
        ".agents/plugins/marketplace.json",
        ".codex-plugin/plugin.json",
        "plugin.json",
        ".ai-rulez/skills/infra-copilot/references/decisions.md.example",
        ".ai-rulez/skills/infra-copilot/references/protocol.md",
        ".ai-rulez/skills/infra-copilot/references/steps.yaml",
        "skills/infra-copilot/references/decisions.md.example",
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


def main() -> int:
    errors = [
        *validate_layout(),
        *validate_skills(),
        *validate_command_tools(),
        *validate_skill_sections(),
        *validate_description_budget(),
        *validate_config_fallbacks(),
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
