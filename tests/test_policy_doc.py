"""Tests that docs/policy.md keeps stating what host rules cannot do.

No permission profile ships, so the document is the whole deliverable. Its
value is the limitations it records — each one was found by review rather than
by reasoning, and each is easy to lose in an edit.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY = REPO_ROOT / "docs/policy.md"
MANIFEST = REPO_ROOT / ".ai-rulez/skills/infra-copilot/references/steps.yaml"


class PolicyDocTests(unittest.TestCase):
    def setUp(self) -> None:
        raw = POLICY.read_text(encoding="utf-8")
        # Collapse whitespace before matching. Asserting on single lines silently
        # misses any phrase the prose happens to wrap — which is how a duplicated
        # word survived review in this same pull request.
        self.policy = re.sub(r"\s+", " ", raw)
        self.raw = raw

    def test_no_deployable_profile_ships(self) -> None:
        """A file that looks authoritative invites being deployed unread."""
        self.assertFalse(
            list(REPO_ROOT.glob("templates/managed-settings/*.json")),
            "policy guidance is documentation; shipping a profile implies guarantees "
            "the grammar cannot provide",
        )

    def test_leads_with_the_conclusion(self) -> None:
        """A reader who stops after one line must not be left writing rules."""
        self.assertIn("cannot meaningfully constrain this plugin", self.policy)

    def test_records_every_known_bypass(self) -> None:
        """Each was found by review, and each is supplied by this plugin's own docs."""
        for bypass in (
            "mise exec -- terraform apply",   # protocol.md recommends the wrapper
            "actions/apply",                  # hcp-api.md ships the REST recipe
            "do not govern Bash",             # Read() rules bind the Read tool only
            "compound shell strings",         # allow-lists cannot match the checks
        ):
            with self.subTest(bypass=bypass):
                self.assertIn(bypass, self.policy)

    def test_records_the_bare_verb_matching_trap(self) -> None:
        # Matched on the distinctive fragment: the sentence contains bold markup
        # (`does **not** match`) which any longer literal would trip over.
        self.assertIn("bare `terraform apply`", self.policy)
        self.assertIn("wildcard needs an argument", self.policy)

    def test_names_only_skill_denies_as_holding(self) -> None:
        self.assertIn("Only `Skill()` denies are robust", self.policy)

    def test_points_at_boundaries_that_would_work(self) -> None:
        self.assertIn("#19", self.policy)
        self.assertIn("Sandbox-level", self.policy)
        self.assertIn("without apply permission", self.policy)

    def test_warns_against_locking_the_rule_set(self) -> None:
        self.assertIn("Do not set `allowManagedPermissionRulesOnly`", self.policy)

    def test_records_the_hcp_token_exception_and_the_real_control(self) -> None:
        self.assertIn("credentials.tfrc.json", self.policy)
        self.assertIn("Do not deny the read", self.policy)
        self.assertIn("Scope the token instead", self.policy)

    def test_records_merge_not_copy(self) -> None:
        self.assertIn("Merge, do not copy", self.policy)

    def test_records_other_hosts_as_unverified(self) -> None:
        self.assertIn("unverified", self.policy.lower())

    def test_the_manifest_still_does_not_apply(self) -> None:
        """The document tells readers to deny apply because nothing needs it."""
        body = MANIFEST.read_text(encoding="utf-8")
        for verb in ("apply", "destroy"):
            self.assertIsNone(
                re.search(rf"\bterraform {verb}\b", body),
                f"the manifest now runs terraform {verb}; revisit docs/policy.md",
            )


if __name__ == "__main__":
    unittest.main()
