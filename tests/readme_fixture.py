"""Render a README that carries the Template's Config block and Decisions table.

The Skills read both from fixed sections of the root README, between marker comments.
Fixtures build that file the same way the Template renders it, so a test states the
rows and the YAML it cares about and never the surrounding markers.
"""

from __future__ import annotations

from pathlib import Path

CONFIG_START = "<!-- infra:config start -->"
CONFIG_END = "<!-- infra:config end -->"
DECISIONS_START = "<!-- infra:decisions start -->"
DECISIONS_END = "<!-- infra:decisions end -->"
CUSTOMIZATION_START = "# infra:customization start"
CUSTOMIZATION_END = "# infra:customization end"


def render(config: str | None = None, decisions: str | None = None) -> str:
    """A README with whichever sections are given; an omitted section is absent."""
    parts = ["# Infra\n"]
    if config is not None:
        body = config if config.endswith("\n") else config + "\n"
        parts.append(f"## Config\n\n{CONFIG_START}\n```yaml\n{body}```\n{CONFIG_END}\n")
    if decisions is not None:
        body = decisions if decisions.endswith("\n") else decisions + "\n"
        parts.append(f"## Decisions\n\n{DECISIONS_START}\n\n{body}\n{DECISIONS_END}\n")
    return "\n".join(parts)


class ReadmeFixture:
    """A README on disk whose Config block and Decisions table change independently."""

    def __init__(self, root: Path) -> None:
        self.path = root / "README.md"
        self._config: str | None = None
        self._decisions: str | None = None

    def config(self, text: str | None) -> Path:
        self._config = text
        return self._write()

    def decisions(self, text: str | None) -> Path:
        self._decisions = text
        return self._write()

    def _write(self) -> Path:
        self.path.write_text(render(self._config, self._decisions), encoding="utf-8")
        return self.path
