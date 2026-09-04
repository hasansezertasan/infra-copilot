"""Tests for the shipped permission profiles.

A profile that drifts from what the plugin actually invokes is worse than none:
with `allowManagedPermissionRulesOnly` set, an allow list missing a command
blocks work rather than merely failing to restrict it.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "templates/managed-settings"
DEFAULT = TEMPLATES / "claude-code.json"
STATUS_ONLY = TEMPLATES / "claude-code-status-only.json"
MANIFEST = REPO_ROOT / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
CHECKS = REPO_ROOT / ".ai-rulez/skills/infra-copilot/references/checks"


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def rules(path: Path, bucket: str) -> list[str]:
    return list(load(path)["permissions"].get(bucket, []))  # type: ignore[index]


class ProfileTests(unittest.TestCase):
    def test_both_profiles_parse(self) -> None:
        for path in (DEFAULT, STATUS_ONLY):
            with self.subTest(profile=path.name):
                self.assertIn("permissions", load(path))

    def test_apply_and_destroy_are_denied_everywhere(self) -> None:
        """They appear nowhere in the manifest, so denying them costs nothing."""
        for path in (DEFAULT, STATUS_ONLY):
            for verb in ("apply", "destroy"):
                with self.subTest(profile=path.name, verb=verb):
                    self.assertIn(f"Bash(terraform {verb} *)", rules(path, "deny"))

    def test_the_manifest_still_does_not_apply(self) -> None:
        """If a future step applies, the deny above becomes a bug rather than a guard."""
        body = MANIFEST.read_text(encoding="utf-8")
        for verb in ("apply", "destroy"):
            self.assertIsNone(
                re.search(rf"\bterraform {verb}\b", body),
                f"the manifest now runs terraform {verb}; revisit docs/policy.md",
            )

    def test_status_only_cannot_reach_the_mutating_skills(self) -> None:
        deny = rules(STATUS_ONLY, "deny")
        for skill in ("setup", "import", "add"):
            with self.subTest(skill=skill):
                self.assertIn(f"Skill(infra-copilot:{skill})", deny)
        self.assertIn("Edit(**)", deny)
        self.assertIn("Write(**)", deny)
        self.assertIn("Skill(infra-copilot:status)", rules(STATUS_ONLY, "allow"))

    def test_every_allowed_command_is_one_the_plugin_uses(self) -> None:
        """The allow list must not grant reach the plugin never needs.

        Derived from the manifest and the shipped check script rather than
        maintained by hand, so a stale entry is a test failure.
        """
        used = set(
            re.findall(
                r"\b(terraform|mise|jq|gh|curl|cf-terraforming|gcloud|git)\b",
                MANIFEST.read_text(encoding="utf-8")
                + "".join(p.read_text(encoding="utf-8") for p in CHECKS.glob("*.sh")),
            )
        )
        for path in (DEFAULT, STATUS_ONLY):
            for rule in rules(path, "allow") + rules(path, "ask"):
                match = re.fullmatch(r"Bash\((\S+).*\)", rule)
                if match is None:
                    continue  # Skill(...) rules
                with self.subTest(profile=path.name, rule=rule):
                    self.assertIn(
                        match.group(1),
                        used,
                        "granted a command the plugin never invokes",
                    )

    def test_credential_read_is_not_denied(self) -> None:
        """Denying it breaks every HCP step; docs/policy.md explains the tradeoff."""
        for path in (DEFAULT, STATUS_ONLY):
            with self.subTest(profile=path.name):
                for rule in rules(path, "deny"):
                    self.assertNotIn("credentials.tfrc.json", rule)

    def test_the_tradeoff_is_documented(self) -> None:
        policy = (REPO_ROOT / "docs/policy.md").read_text(encoding="utf-8")
        self.assertIn("credentials.tfrc.json", policy)
        self.assertIn("HCP token", policy)


if __name__ == "__main__":
    unittest.main()
