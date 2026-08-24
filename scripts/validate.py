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
JSON_MANIFESTS = (
    ".agents/plugins/marketplace.json",
    ".claude-plugin/marketplace.json",
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    "plugin.json",
)
TOOL_PIN_SPECS = {
    "ai-rulez": "INFRA_COPILOT_AI_RULEZ_VERSION",
    "skills": "INFRA_COPILOT_SKILLS_VERSION",
}
TOOL_PIN_WORKFLOWS = (
    ".github/workflows/check.yml",
    ".github/workflows/release.yml",
)
VERSION_PATTERN = r"[0-9]+(?:\.[0-9]+){2}(?:[-+][0-9A-Za-z.-]+)?"


def load_json(path: str) -> dict[str, object]:
    with (ROOT / path).open(encoding="utf-8") as source:
        return json.load(source)


def validate_links(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    repository_root = root.resolve()
    for markdown in sorted(repository_root.rglob("*.md")):
        if IGNORED_DIRECTORIES.intersection(markdown.parts):
            continue
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
                    f"{markdown.relative_to(repository_root)}: link "
                    f"{raw_target!r} resolves outside the repository"
                )
                continue
            if not resolved.exists():
                errors.append(
                    f"{markdown.relative_to(repository_root)}: broken link {raw_target!r}"
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


def validate_json_manifests(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for relative in JSON_MANIFESTS:
        try:
            with (root / relative).open(encoding="utf-8") as source:
                json.load(source)
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{relative}: invalid JSON manifest: {error}")
    return errors


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
    errors: list[str] = []
    readme = (root / "README.md").read_text(encoding="utf-8")
    for package, variable in TOOL_PIN_SPECS.items():
        observed: dict[str, str] = {}
        for relative in TOOL_PIN_WORKFLOWS:
            workflow = (root / relative).read_text(encoding="utf-8")
            match = re.search(
                rf"^\s*{re.escape(variable)}:\s*(?P<version>{VERSION_PATTERN})\s*$",
                workflow,
                re.MULTILINE,
            )
            if match is None:
                errors.append(f"{relative}: missing {variable}")
            else:
                observed[relative] = match.group("version")
        documented = set(
            re.findall(rf"{re.escape(package)}@(?P<version>{VERSION_PATTERN})", readme)
        )
        versions = set(observed.values()) | documented
        if not documented:
            errors.append(f"README.md: missing pinned {package} command")
        if len(versions) > 1:
            details = ", ".join(sorted(versions))
            errors.append(f"{package}: inconsistent pinned versions: {details}")
    return errors


def toml_string(path: str, table: str, key: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
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


def validate_versions() -> list[str]:
    errors: list[str] = []
    expected = toml_string(".ai-rulez/config.toml", "plugin", "version")

    actual = {
        ".claude-plugin/marketplace.json": str(
            load_json(".claude-plugin/marketplace.json")["plugins"][0]["version"]  # type: ignore[index]
        ),
        ".claude-plugin/plugin.json": str(
            load_json(".claude-plugin/plugin.json")["version"]
        ),
        ".codex-plugin/plugin.json": str(
            load_json(".codex-plugin/plugin.json")["version"]
        ),
        ".agents/plugins/marketplace.json": str(
            load_json(".agents/plugins/marketplace.json")["plugins"][0]["version"]  # type: ignore[index]
        ),
    }

    for path, version in actual.items():
        if version != expected:
            errors.append(f"{path}: version {version!r} != {expected!r}")
    return errors


def validate_layout() -> list[str]:
    required = (
        ".github/renovate.json",
        ".github/workflows/check.yml",
        ".github/workflows/release.yml",
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
        *validate_config_fallbacks(),
        *validate_json_manifests(),
        *validate_manifest_paths(),
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
