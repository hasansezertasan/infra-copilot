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
        self.assertIn("Claude Code's command-level permission rules", self.policy)

    def test_records_every_known_bypass(self) -> None:
        """Each was found by review, and each is supplied by this plugin's own docs."""
        for bypass in (
            "mise exec -- terraform apply",   # protocol.md recommends the wrapper
            "actions/apply",                  # hcp-api.md ships the REST recipe
            "do not govern Bash",             # Read() rules bind the Read tool only
            "compound shell strings",         # allow-lists cannot match the checks
            "second entry point",             # /infra-setup bypasses the Skill deny
            "/tmp/cf_token",                  # the import discovery token
        ):
            with self.subTest(bypass=bypass):
                self.assertIn(bypass, self.policy)

    def test_records_the_bare_verb_matching_trap(self) -> None:
        # Matched on the distinctive fragment: the sentence contains bold markup
        # (`does **not** match`) which any longer literal would trip over.
        self.assertIn("bare `terraform apply`", self.policy)
        self.assertIn("wildcard needs an argument", self.policy)

    def test_claims_no_rule_type_holds(self) -> None:
        """An earlier draft called Skill() denies load-bearing; the command surface
        is why that was wrong, so the document must not walk it back."""
        self.assertIn("Nothing in the table holds", self.policy)
        self.assertNotIn("Only `Skill()` denies are robust", self.policy)

    def test_does_not_promise_apply_is_human_only(self) -> None:
        """The same document documents the REST bypass; both cannot be true."""
        self.assertNotIn("Applying is a human action", self.policy)
        self.assertIn("nothing here enforces that", self.policy)

    def test_points_at_boundaries_that_would_work(self) -> None:
        self.assertIn("Sandbox-level", self.policy)
        self.assertIn("lower-privilege identity", self.policy)

    def test_does_not_present_the_subagent_as_enforcement(self) -> None:
        """The subagent cannot enforce change-nothing, and saying so is the point.

        status runs 21 shell checks so it needs Bash, and this document
        establishes that Bash writes files. An earlier draft named the subagent
        as the mechanism that would enforce the promise, which contradicted
        the same page's own bypass 3.
        """
        self.assertIn("does **not** enforce", self.policy)
        self.assertIn("only a sandboxed command runner", self.policy.lower())
        self.assertNotIn("only mechanism that makes `status`", self.policy)

    def test_does_not_reproduce_claude_owned_path_values(self) -> None:
        """Those paths are Claude's to change, and two findings here were that drift.

        The page links to Claude's settings documentation instead of copying a
        table that can silently go stale.
        """
        for owned in (
            "/Library/Application Support/ClaudeCode",
            "/etc/claude-code/",
            "Program Files",
        ):
            with self.subTest(value=owned):
                self.assertNotIn(owned, self.raw)
        self.assertIn("code.claude.com/docs/en/settings", self.policy)

    def test_qualifies_the_managed_rules_lock(self) -> None:
        """Whether an unmatched command blocks or prompts depends on permission mode.

        An earlier draft asserted a hard block unconditionally, which would
        have talked administrators out of the field for the wrong reason.
        """
        self.assertIn("allowManagedPermissionRulesOnly", self.policy)
        self.assertIn("depends on the active permission mode", self.policy)
        self.assertNotIn("becomes a hard block", self.policy)

    def test_records_the_hcp_token_exception_and_the_real_control(self) -> None:
        self.assertIn("credentials.tfrc.json", self.policy)
        self.assertIn("Do not deny the read", self.policy)

    def test_does_not_advise_scoping_a_user_token(self) -> None:
        """terraform login mints a user token, which carries the user's permissions.

        There is no apply scope to remove from it, so the control is a
        different principal — which phase 0 does not provision.
        """
        self.assertIn("Use a separate, lower-privilege identity", self.policy)
        self.assertNotIn("Scope the token instead", self.policy)

    def test_marks_the_compound_bypass_as_unverified(self) -> None:
        """Claude documents per-segment evaluation, which may invalidate bypass 4."""
        self.assertIn("This one is unverified, and may be wrong", self.policy)

    def test_records_merge_not_copy(self) -> None:
        self.assertIn("Merge, do not copy", self.policy)

    def test_records_other_hosts_as_unverified(self) -> None:
        self.assertIn("unverified", self.policy.lower())

    def test_the_manifest_still_does_not_apply(self) -> None:
        """The document tells readers to deny apply because nothing needs it."""
        body = MANIFEST.read_text(encoding="utf-8")
        # Global options may precede the subcommand: `terraform -chdir=DIR apply` is
        # valid, and a verb-immediately-after-terraform pattern misses it. Same rigid
        # shape assumption that made `Bash(terraform apply *)` miss a bare apply.
        for verb in ("apply", "destroy"):
            self.assertIsNone(
                re.search(rf"\bterraform\b(?:\s+-\S+)*\s+{verb}\b", body),
                f"the manifest now runs terraform {verb}; revisit docs/policy.md",
            )

    def test_the_apply_guard_sees_global_options(self) -> None:
        """Pin the matcher itself, since its whole value is catching a future edit."""
        pattern = re.compile(r"\bterraform\b(?:\s+-\S+)*\s+apply\b")
        for command in (
            "terraform apply",
            "terraform -chdir=terraform/cloudflare apply",
            "terraform -no-color -chdir=x apply -auto-approve",
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(pattern.search(command))
        self.assertIsNone(pattern.search("terraform plan"))


if __name__ == "__main__":
    unittest.main()
