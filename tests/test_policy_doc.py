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
        self.policy = POLICY.read_text(encoding="utf-8")

    def test_no_deployable_profile_ships(self) -> None:
        """A file that looks authoritative invites being deployed unread."""
        self.assertFalse(
            list(REPO_ROOT.glob("templates/managed-settings/*.json")),
            "policy guidance is documentation; shipping a profile implies guarantees "
            "the grammar cannot provide",
        )

    def test_records_the_bare_verb_matching_trap(self) -> None:
        self.assertIn("does not match a bare `terraform apply`", self.policy)

    def test_records_that_an_allow_list_cannot_bound_the_plugin(self) -> None:
        self.assertIn("compound shell strings", self.policy)

    def test_records_that_read_only_is_not_enforceable(self) -> None:
        self.assertIn("Read-only cannot be enforced at the command level", self.policy)
        self.assertIn("#19", self.policy)

    def test_records_the_hcp_token_exception(self) -> None:
        self.assertIn("credentials.tfrc.json", self.policy)
        self.assertIn("Do not deny that read", self.policy)

    def test_records_merge_not_copy(self) -> None:
        self.assertIn("Merge, do not copy", self.policy)

    def test_records_other_hosts_as_unverified(self) -> None:
        self.assertIn("unverified", self.policy)

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
