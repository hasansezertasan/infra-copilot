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

    def test_apply_and_destroy_are_denied_in_both_forms(self) -> None:
        """`Bash(terraform apply *)` does not match a bare `terraform apply`.

        The wildcard needs an argument, so the bare form falls through to
        default handling — and `terraform apply` with no arguments is the
        common invocation.
        """
        for path in (DEFAULT, STATUS_ONLY):
            deny = rules(path, "deny")
            for verb in ("apply", "destroy"):
                for rule in (f"Bash(terraform {verb})", f"Bash(terraform {verb} *)"):
                    with self.subTest(profile=path.name, rule=rule):
                        self.assertIn(rule, deny)

    def test_neither_profile_locks_the_rule_set(self) -> None:
        """A locked list that misses a command blocks work instead of restricting it.

        The status scan runs twelve curl-based checks and launches a shipped
        shell script, so the lock is left to the operator after they have
        exercised the profile.
        """
        for path in (DEFAULT, STATUS_ONLY):
            with self.subTest(profile=path.name):
                self.assertNotIn("allowManagedPermissionRulesOnly", load(path))

    def test_status_scan_commands_are_all_grantable(self) -> None:
        """With no lock these degrade to prompts, but an omission is still friction.

        preflight runs `gh --version` and `curl --version`, most checks use
        `curl`, and the shipped check is launched through `sh`.
        """
        granted = " ".join(rules(STATUS_ONLY, "allow") + rules(STATUS_ONLY, "ask"))
        for needed in ("gh --version", "curl --version", "curl *", "sh *"):
            with self.subTest(command=needed):
                self.assertIn(needed, granted)

    def test_legacy_config_fallback_is_not_denied(self) -> None:
        """config.md and the README both name it as a supported migration path."""
        for path in (DEFAULT, STATUS_ONLY):
            with self.subTest(profile=path.name):
                for rule in rules(path, "deny"):
                    self.assertNotIn("infra-copilot.local.md", rule)

    def test_secret_denies_reach_nested_terraform_roots(self) -> None:
        """Leaves live under terraform/cloudflare and terraform/github."""
        deny = rules(DEFAULT, "deny")
        self.assertIn("Read(./**/*.tfvars)", deny)
        self.assertIn("Read(./**/.env)", deny)

    def test_the_compound_command_limitation_is_documented(self) -> None:
        """Readers must not take the Bash allow-list for the enforcement boundary."""
        policy = (REPO_ROOT / "docs/policy.md").read_text(encoding="utf-8")
        self.assertIn("compound shell strings", policy)
        self.assertIn("documentation of intent", policy)
        self.assertIn("has been exercised against a live session", policy.replace(
            "has not been exercised against a live session",
            "has been exercised against a live session"))

    def test_the_read_only_limitation_is_documented(self) -> None:
        """The profile must not claim an enforcement the grammar cannot provide."""
        policy = (REPO_ROOT / "docs/policy.md").read_text(encoding="utf-8")
        self.assertIn("does not enforce read-only", policy)
        comment = " ".join(load(STATUS_ONLY)["$comment"])  # type: ignore[arg-type]
        self.assertIn("speed bump, not a boundary", comment)

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

    #: Utilities the compound checks spawn but which are deliberately not granted:
    #: enumerating them would allow `rm` and `sed` broadly and gate nothing, because a
    #: prefix rule cannot match a check that begins with a variable assignment.
    UNGRANTED_UTILITIES = frozenset(
        {"mktemp", "grep", "sed", "awk", "head", "tr", "rm", "printf", "test", "cd"}
    )

    def test_ungranted_utilities_are_really_used_by_the_checks(self) -> None:
        """Pin the exclusion, so it reads as a decision rather than an oversight."""
        body = MANIFEST.read_text(encoding="utf-8") + "".join(
            p.read_text(encoding="utf-8") for p in CHECKS.glob("*.sh")
        )
        for utility in self.UNGRANTED_UTILITIES:
            with self.subTest(utility=utility):
                self.assertRegex(body, rf"\b{utility}\b")
        granted = " ".join(rules(DEFAULT, "allow") + rules(DEFAULT, "ask"))
        for utility in self.UNGRANTED_UTILITIES:
            with self.subTest(utility=utility, granted=False):
                self.assertNotIn(f"Bash({utility}", granted)

    def test_every_allowed_command_is_one_the_plugin_uses(self) -> None:
        """The allow list must not grant reach the plugin never needs.

        Derived from the manifest and the shipped check script rather than
        maintained by hand, so a stale entry is a test failure.
        """
        used = set(
            re.findall(
                r"\b(terraform|mise|jq|gh|curl|cf-terraforming|gcloud|git|sh)\b",
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
