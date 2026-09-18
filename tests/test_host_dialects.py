"""The per-host capability table and the parity gate that keeps it honest.

Three surfaces need the same per-host fact -- the question tool a decision may
use, the dialect a subagent manifest must be written in, and the path a host
discovers a hook manifest at -- and `ai-rulez` generates none of them. These
tests are what stands in for a generator: they fail when a shipped artifact and
its record in hosts.yaml disagree.

Each case below is a failure that actually happened while establishing the
table, not a hypothetical.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate import (
    AGENT_REQUIRED_TOOLS,
    COMMAND_TOOLS,
    AGENT_STEM,
    DELEGATION_MARKERS,
    AGENT_FORBIDDEN_PATH,
    EXPECTED_HOSTS,
    HOSTS_DOCUMENT,
    QUESTION_PROTOCOL_DOCUMENT,
    _field,
    _verified,
    host_records,
    validate_host_dialects,
    validate_question_protocol,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
#: Everything the two validators read. Copied per test so a case can corrupt one
#: file without the others going missing and masking the error under test.
FIXTURE_PATHS = (
    HOSTS_DOCUMENT,
    QUESTION_PROTOCOL_DOCUMENT,
    "hooks/hooks.json",
    "hooks/session-start.sh",
    f"agents/{AGENT_STEM}.md",
)
#: The single host whose agent actually ships. Read from the table rather than
#: named here, so this file cannot drift from it either.
AGENT_HOST = next(
    host for host, block in host_records(REPO_ROOT).items() if _verified(block, "agent")
)
AGENT_PATH = f"{_field(host_records(REPO_ROOT)[AGENT_HOST], 'agent', 'path').rstrip('/')}/{AGENT_STEM}.md"


def build_root(directory: str) -> Path:
    root = Path(directory)
    for relative in FIXTURE_PATHS:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / relative, destination)
    return root


class HostRecordTests(unittest.TestCase):
    def test_exactly_one_host_owns_the_agent(self) -> None:
        """Root agents/ is one path with incompatible dialects, so only one can."""
        owners = [h for h, b in host_records(REPO_ROOT).items() if _verified(b, "agent")]
        self.assertEqual(owners, [AGENT_HOST], owners)

    def test_verified_flags_survive_a_trailing_comment(self) -> None:
        """A trailing comment is this file's dominant style.

        An anchored `$` after the flag turned every commented record into
        "unrecorded", which silently disabled the rules keyed on them -- the
        Claude hook rules among them.
        """
        records = host_records(REPO_ROOT)
        self.assertTrue(_verified(records["claude"], "hook"))
        self.assertIsNotNone(_verified(records["claude"], "question_tool"))

    def test_a_nested_key_cannot_clobber_a_real_record(self) -> None:
        """Keys under a later top-level mapping are not hosts.

        Matching any two-space-indented key anywhere reset the record to empty,
        and an empty block passes every rule while the gate reports green.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8")
                + "\ndefaults:\n  claude:\n    display_name: not a host\n",
                encoding="utf-8",
            )
            records = host_records(root)
            self.assertIn("display_name: Claude Code", records["claude"])
            self.assertEqual(validate_host_dialects(root), [])

    def test_repository_is_currently_consistent(self) -> None:
        self.assertEqual(validate_host_dialects(REPO_ROOT), [])
        self.assertEqual(validate_question_protocol(REPO_ROOT), [])


class AgentDialectTests(unittest.TestCase):
    def test_a_foreign_dialect_in_the_shipped_slot_is_rejected(self) -> None:
        """The failure this whole table exists for, and it is silent both ways.

        Antigravity reported "agents: 1 processed" for Claude's comma-string form
        and then never listed the agent in `agy agent`. In the other direction,
        `claude plugin details` showed "Agents (1)" for an Antigravity-dialect
        file at root agents/ -- an agent whose whole tool grant is names Claude
        does not have.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / AGENT_PATH
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "tools: Read, Bash, Glob, Grep, Skill",
                    "tools:\n  - view_file\n  - grep_search\n  - run_command",
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("dialect" in error for error in validate_host_dialects(root)),
            )

    def test_a_write_tool_in_the_record_is_rejected(self) -> None:
        """The scan is read-only and the recorded grant is what says so."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "tool_names: [Read, Bash, Glob, Grep, Skill]",
                    "tool_names: [Read, Bash, Glob, Grep, Skill, Write]",
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("Write" in error for error in validate_host_dialects(root)),
            )

    def test_an_agent_that_restates_the_scan_is_rejected(self) -> None:
        """A second copy of the runbook is a second behavioural authority."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / AGENT_PATH
            document.write_text(
                document.read_text(encoding="utf-8").replace("status.md", "my own inlined procedure"),
                encoding="utf-8",
            )
            self.assertTrue(
                any("delegate" in error for error in validate_host_dialects(root)),
            )

    def test_renaming_a_tool_in_the_table_fails_the_shipped_file(self) -> None:
        """The table is authoritative: editing it is what moves the gate."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "tool_names: [Read, Bash, Glob, Grep, Skill]",
                    "tool_names: [Read, Bash, Glob, Skill]",
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("dialect" in error for error in validate_host_dialects(root)),
            )


class HookManifestTests(unittest.TestCase):
    def test_extra_top_level_key_in_the_root_manifest_is_rejected(self) -> None:
        """Antigravity counted a "_comment" sibling of "hooks" as a second hook.

        `agy plugin validate` reported "hooks: 2 processed" for a file declaring
        one, so a JSON comment key ships a junk hook rather than documentation.
        The rule covers every recorded manifest, not just the one host that
        miscounts: no manifest has a comment syntax to fall back on.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            manifest = root / "hooks/hooks.json"
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["_comment"] = ["why this file exists"]
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            self.assertTrue(
                any("top-level keys" in error for error in validate_host_dialects(root)),
            )

    def test_a_manifest_no_record_verifies_is_rejected(self) -> None:
        """Codex's is absent on purpose; shipping it back must fail.

        Codex 0.154.0 fired no SessionStart hook from any candidate path, with
        or without `--enable plugin_hooks`.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            (root / "hooks/hooks-codex.json").write_text("{}", encoding="utf-8")
            self.assertTrue(
                any("hooks-codex.json" in error for error in validate_host_dialects(root)),
            )

    def test_a_verified_host_missing_its_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            (root / "hooks/hooks.json").unlink()
            self.assertTrue(
                any("ships no manifest" in error for error in validate_host_dialects(root)),
            )

    def test_a_root_variable_the_script_ignores_is_rejected(self) -> None:
        """The manifest guard and the output-shape branch must agree.

        A host exporting only the variable the script does not test runs the
        hook and then has its announcement emitted in another host's shape.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            script = root / "hooks/session-start.sh"
            script.write_text(
                script.read_text(encoding="utf-8").replace(
                    "${CLAUDE_PLUGIN_ROOT:-}", "${SOME_OTHER_ROOT:-}"
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("wrong shape" in error for error in validate_host_dialects(root)),
            )


class ReviewRegressionTests(unittest.TestCase):
    """Each case is a hole the PR review found in the gate itself."""

    def test_a_comment_between_entries_does_not_truncate_the_table(self) -> None:
        """An unindented comment is ordinary YAML, not a top-level key.

        Treating it as one closed the mapping and silently dropped every host
        after it -- and since each rule iterates the records returned, the gate
        stayed green while three of the four hosts stopped being checked.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "  antigravity:", "# --- an ordinary separator ---\n  antigravity:", 1
                ),
                encoding="utf-8",
            )
            self.assertEqual(set(host_records(root)), set(EXPECTED_HOSTS))
            self.assertEqual(validate_host_dialects(root), [])

    def test_a_dropped_host_fails_rather_than_going_unchecked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            text = document.read_text(encoding="utf-8")
            document.write_text(text[: text.index("  opencode:")], encoding="utf-8")
            self.assertTrue(
                any("opencode" in error for error in validate_host_dialects(root)),
            )

    def test_wiring_at_an_unverified_path_is_rejected_whatever_its_dialect(self) -> None:
        """Codex records `toml_inherited` with no tool names.

        Gating the rejection on a renderable dialect meant nothing shipped under
        .codex/agents/ could ever be reported, though the rule promises to reject
        every artifact at an unverified path.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            manifest = root / ".codex/agents/infra-auditor.toml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text('name = "infra-auditor"\n', encoding="utf-8")
            self.assertTrue(
                any(".codex/agents" in error for error in validate_host_dialects(root)),
            )

    def test_the_shared_agent_directory_is_not_reported_as_unverified(self) -> None:
        """Antigravity's unverified path IS Claude's verified one.

        The owner's dialect rule governs that file; reporting it twice would make
        the collision unshippable rather than recorded.
        """
        self.assertEqual(validate_host_dialects(REPO_ROOT), [])

    def test_a_hook_matcher_that_contradicts_the_record_is_rejected(self) -> None:
        """Antigravity takes "*" and Claude an explicit source list.

        A manifest carrying the wrong one is discovered and then never fires, and
        nothing compared the manifest against the recorded matcher.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            manifest = root / "hooks/hooks.json"
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["hooks"]["SessionStart"][0]["matcher"] = "something-else"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            self.assertTrue(
                any("matcher" in error for error in validate_host_dialects(root)),
            )

    def test_a_repo_relative_runbook_path_is_rejected(self) -> None:
        """The agent's working directory is the CONSUMING repository.

        A repo-relative `skills/infra-copilot/...` resolves into the consumer and
        finds nothing; it only looks correct from a source checkout of this repo.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / AGENT_PATH
            document.write_text(
                document.read_text(encoding="utf-8")
                + f"\nAlso read {AGENT_FORBIDDEN_PATH}status.md directly.\n",
                encoding="utf-8",
            )
            self.assertTrue(
                any("consuming repository" in error for error in validate_host_dialects(root)),
            )


class SecondReviewRegressionTests(unittest.TestCase):
    """Holes found by the review of the first round of review fixes."""

    def test_a_record_with_no_verification_state_is_rejected(self) -> None:
        """An unstated flag disabled every rule keyed on it.

        Deleting one `verified:` line left validate_host_dialects() green and a
        nonsense matcher passed with it -- the gate was simply off for that
        artifact rather than failing.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            text = document.read_text(encoding="utf-8")
            start = text.index("      path: hooks/hooks.json")
            flag = text.index("      verified:", start)
            document.write_text(
                text[:flag] + text[text.index("\n", flag) + 1 :], encoding="utf-8"
            )
            self.assertTrue(
                any("usable `verified:` flag" in e for e in validate_host_dialects(root)),
            )

    def test_two_hosts_may_not_own_the_same_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            text = document.read_text(encoding="utf-8")
            start = text.index("  antigravity:")
            flag = text.index("      verified: false", text.index("    agent:", start))
            document.write_text(
                text[:flag] + "      verified: true" + text[flag + len("      verified: false") :],
                encoding="utf-8",
            )
            self.assertTrue(
                any("only one may" in e for e in validate_host_dialects(root)),
            )

    def test_the_antigravity_hook_is_not_shipped(self) -> None:
        """Discovery is not execution, and the table says so.

        `agy plugin validate` proves the root manifest is found; no probe hook
        ever fired there, in print mode or an interactive TUI session. Codex is
        excluded on exactly that basis, so this has to be too.
        """
        self.assertFalse((REPO_ROOT / "hooks.json").exists())
        self.assertFalse(_verified(host_records(REPO_ROOT)["antigravity"], "hook"))

    def test_a_root_manifest_shipped_anyway_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            (root / "hooks.json").write_text('{"hooks": {}}', encoding="utf-8")
            self.assertTrue(
                any("hooks.json" in e and "unverified" in e for e in validate_host_dialects(root)),
            )


class ThirdReviewRegressionTests(unittest.TestCase):
    """Holes the third review round found in the gate."""

    def test_the_grant_is_read_from_frontmatter_not_the_whole_document(self) -> None:
        """A whole-file search let the frontmatter grant `Write`.

        The expected line sitting anywhere in the prose satisfied it, and the
        forbidden-tool check looked only at hosts.yaml -- so Claude would have
        loaded a write-capable auditor behind a green gate.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / AGENT_PATH
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "tools: Read, Bash, Glob, Grep, Skill", "tools: Write", 1
                )
                + "\n\nFor reference: tools: Read, Bash, Glob, Grep, Skill\n",
                encoding="utf-8",
            )
            self.assertTrue(
                any("frontmatter tools" in e for e in validate_host_dialects(root)),
            )

    def test_codex_can_graduate_in_its_own_recorded_format(self) -> None:
        """`toml_inherited` names no tools on purpose, and its file is .toml.

        Rejecting the empty list as incomplete -- and then assuming Claude's .md
        filename -- meant the row could only pass by falsifying hosts.yaml.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    """      tools_dialect: toml_inherited # no tools key; the session's tools are inherited
      tool_names: []
      verified: false""",
                    """      tools_dialect: toml_inherited # no tools key; the session's tools are inherited
      tool_names: []
      verified: true""",
                ),
                encoding="utf-8",
            )
            shipped = root / ".codex/agents"
            shipped.mkdir(parents=True)
            (shipped / f"{AGENT_STEM}.toml").write_text(
                'name = "infra-auditor"\n'
                'developer_instructions = """Invoke the infra-copilot skill, then status.md."""\n',
                encoding="utf-8",
            )
            self.assertEqual(validate_host_dialects(root), [])

    def test_a_dialect_that_renders_tools_may_not_leave_them_empty(self) -> None:
        """The schema pass now owns this: `[]` is rejected as an empty list before
        the owner loop runs, which also covers the dialects this test cannot reach.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "tool_names: [Read, Bash, Glob, Grep, Skill]", "tool_names: []", 1
                ),
                encoding="utf-8",
            )
            errors = validate_host_dialects(root)
            self.assertTrue(
                any("empty list" in e or "names no tools" in e for e in errors), errors
            )

    def test_the_protocol_table_must_match_the_records(self) -> None:
        """The protocol reproduces the table as prose a reader acts on.

        Flipping a host's `verified` left `make check` green while the protocol
        still advertised the old capability -- two documents disagreeing about
        whether the native question call is permitted.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "      verified: true  # declared in commands/*.md allowed-tools and available in-session",
                    "      verified: false",
                    1,
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("permits the native" in e for e in validate_question_protocol(root)),
            )

    def test_narrowing_recorded_modes_fails_the_protocol_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "      modes: [binary, single, multi]\n      choices: [2, 4]\n      verified: true",
                    "      modes: [binary, single]\n      choices: [2, 4]\n      verified: true",
                    1,
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("modes cell" in e for e in validate_question_protocol(root)),
            )

    def test_hook_root_variables_come_from_every_recorded_manifest(self) -> None:
        """A hardcoded path pair skipped Codex's manifest once it graduated."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    '      matcher: "*"\n      verified: false\n      # NOT SHIPPED. Codex 0.154.0',
                    '      matcher: "*"\n      verified: true\n      # graduated. Codex 0.154.0',
                    1,
                ),
                encoding="utf-8",
            )
            (root / "hooks/hooks-codex.json").write_text(
                json.dumps(
                    {"hooks": {"SessionStart": [{"matcher": "*", "hooks": [
                        {"type": "command", "command": 'r="${NOVEL_PLUGIN_ROOT:-}"; sh "$r/x"'}
                    ]}]}}
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("wrong shape" in e for e in validate_host_dialects(root)),
            )

    def test_the_agent_manifest_stays_an_adapter(self) -> None:
        """The runbook owns scope, guardrails and the report contract.

        A manifest with room to restate them will, and then drift from them.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / AGENT_PATH
            document.write_text(
                document.read_text(encoding="utf-8") + "\n" * 45, encoding="utf-8"
            )
            self.assertTrue(
                any("adapter" in e for e in validate_host_dialects(root)),
            )


class FourthReviewRegressionTests(unittest.TestCase):
    """Holes the fourth review round found in the third round's fixes."""

    def test_the_declared_agent_name_is_parsed_not_searched(self) -> None:
        """A whole-document search passed a renamed manifest.

        `name: wrong-agent` in the frontmatter still matched, because the stem
        appeared in the heading and the instructions below it -- leaving a file
        that no longer declares the agent the protocol delegates to.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / AGENT_PATH
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    f"name: {AGENT_STEM}", "name: wrong-agent", 1
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("declares name" in e for e in validate_host_dialects(root)),
            )

    def test_a_manifest_with_no_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / AGENT_PATH
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    f"name: {AGENT_STEM}\n", "", 1
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("no agent name" in e for e in validate_host_dialects(root)),
            )

    def test_delegation_is_gated_on_the_recorded_agent(self) -> None:
        """Supporting subagents is not the same as having this one.

        Antigravity supports them and loads nothing from the shared root
        agents/, so a rule keyed on "offers subagents" would call an agent that
        is not there instead of running the scan inline.
        """
        for marker in DELEGATION_MARKERS:
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as directory:
                root = build_root(directory)
                document = root / QUESTION_PROTOCOL_DOCUMENT
                document.write_text(
                    document.read_text(encoding="utf-8").replace(marker, "REMOVED"),
                    encoding="utf-8",
                )
                self.assertTrue(
                    any("delegation rule" in e for e in validate_question_protocol(root)),
                )

    def test_only_a_verified_agent_host_is_recorded_today(self) -> None:
        """The protocol's promise and the table must agree on who has the agent."""
        records = host_records(REPO_ROOT)
        self.assertTrue(_verified(records["claude"], "agent"))
        self.assertFalse(_verified(records["antigravity"], "agent"))


class FifthReviewRegressionTests(unittest.TestCase):
    """One defect, found four ways: a field that goes missing switched off the
    rules keyed on it instead of failing. A schema pass now runs before any rule
    reads a field, so these are regression tests for the class, not four patches.
    """

    def _mutated(self, replacement: tuple[str, str], path: str = HOSTS_DOCUMENT):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / path
        old, new = replacement
        text = document.read_text(encoding="utf-8")
        self.assertIn(old, text)
        document.write_text(text.replace(old, new, 1), encoding="utf-8")
        return root

    def test_a_nulled_hook_path_does_not_disable_its_checks(self) -> None:
        """Nulling Claude's path skipped the verified and parity checks entirely
        while hooks/hooks.json still shipped."""
        root = self._mutated(("      path: hooks/hooks.json", "      path: null"))
        self.assertTrue(any("is null" in e for e in validate_host_dialects(root)))

    def test_deleted_capability_fields_are_reported(self) -> None:
        """Both validators skipped the comparison and reported nothing, so the
        table stopped authorizing claims the protocol still made."""
        root = self._mutated(
            (
                "      modes: [binary, single, multi]\n      choices: [2, 4]\n      verified: true  # declared",
                "      verified: true  # declared",
            )
        )
        errors = validate_host_dialects(root)
        self.assertTrue(any("declares no modes" in e for e in errors), errors)
        self.assertTrue(any("declares no choices" in e for e in errors), errors)

    def test_the_agent_must_keep_the_tools_its_instructions_need(self) -> None:
        """It is told to load the runbook through the skill tool, and its scan
        runs shell checks; dropping either made every delegated run fail."""
        for required in AGENT_REQUIRED_TOOLS["claude"]:
            with self.subTest(tool=required):
                root = self._mutated(
                    (
                        "tool_names: [Read, Bash, Glob, Grep, Skill]",
                        "tool_names: ["
                        + ", ".join(
                            n for n in ("Read", "Bash", "Glob", "Grep", "Skill") if n != required
                        )
                        + "]",
                    )
                )
                self.assertTrue(
                    any(f"omit {required!r}" in e for e in validate_host_dialects(root)),
                )

    def test_the_delegation_gate_is_read_from_its_own_section(self) -> None:
        """Inverting the condition to `verified: false` left the marker satisfied
        by the unrelated question-tool section, re-permitting an unverified host."""
        root = self._mutated(
            (
                # Wrap-independent: the sentence is re-flowed whenever the section
                # is edited, and the test should track the condition, not the line.
                "`agent` as `verified: true`",
                "`agent` as `verified: false`",
            ),
            QUESTION_PROTOCOL_DOCUMENT,
        )
        self.assertTrue(
            any("delegation rule" in e for e in validate_question_protocol(root)),
        )


class SixthReviewRegressionTests(unittest.TestCase):
    """The table must be able to unship things, and must not contradict itself."""

    def test_the_table_can_revoke_the_agent(self) -> None:
        """Layout used to pin the path, and main() short-circuits on layout.

        Recording `agent.verified: false` and removing the manifest is the valid
        way to unship it; the hardcoded entry made that fail `make check` and
        could force an obsolete auto-discovered file to stay.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            (root / AGENT_PATH).unlink()
            document = root / HOSTS_DOCUMENT
            text = document.read_text(encoding="utf-8")
            start = text.index("      path: agents/")
            flag = text.index("      verified: true", start)
            document.write_text(
                text[:flag] + "      verified: false" + text[flag + len("      verified: true") :],
                encoding="utf-8",
            )
            self.assertEqual(validate_host_dialects(root), [])

    def test_a_verified_agent_still_requires_its_manifest(self) -> None:
        """Dropping the layout entry must not drop the requirement with it."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            (root / AGENT_PATH).unlink()
            self.assertTrue(
                any("ships no manifest" in e for e in validate_host_dialects(root)),
            )

    def test_a_duplicate_host_record_is_rejected(self) -> None:
        """The reader appended the second block to the first and every field read
        returned the first occurrence, so a complete contradictory record passed."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8")
                + "\n  claude:\n    display_name: Impostor\n",
                encoding="utf-8",
            )
            self.assertTrue(
                any("duplicate host record" in e for e in validate_host_dialects(root)),
            )

    def test_only_status_may_reach_the_subagent(self) -> None:
        """The action skills must run their resume scan inline, so granting them
        Task hands three commands a capability their instructions forbid."""
        for command, tools in COMMAND_TOOLS.items():
            with self.subTest(command=command):
                self.assertEqual("Task" in tools, command == "infra-status.md")


class SeventhReviewRegressionTests(unittest.TestCase):
    def test_the_table_can_revoke_the_hook(self) -> None:
        """Layout pinned hooks/hooks.json the way it pinned the agent.

        Revoking the record and removing the manifest is the valid table-driven
        state; the fixed list made it fail `make check` first.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            (root / "hooks/hooks.json").unlink()
            document = root / HOSTS_DOCUMENT
            text = document.read_text(encoding="utf-8")
            start = text.index("      path: hooks/hooks.json")
            flag = text.index("      verified: true", start)
            document.write_text(
                text[:flag] + "      verified: false" + text[flag + len("      verified: true") :],
                encoding="utf-8",
            )
            self.assertEqual(validate_host_dialects(root), [])

    def test_a_verified_hook_still_requires_its_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            (root / "hooks/hooks.json").unlink()
            self.assertTrue(
                any("ships no manifest" in e for e in validate_host_dialects(root)),
            )

    def test_the_delegation_rule_does_not_narrow_the_report(self) -> None:
        """Delegation moves where the scan runs, never what it reports.

        The runbook's report is preflight, phase table and verdict; saying the
        agent returns "just" the table and verdict let the preflight line be
        dropped, which is where a missing or drifted tool pin shows up.
        """
        protocol = (REPO_ROOT / QUESTION_PROTOCOL_DOCUMENT).read_text(encoding="utf-8")
        section = protocol[protocol.index("### Running the scan in an isolated context") :]
        section = section[: section.index("\n### ", 1)]
        self.assertIn("in full", section)
        self.assertIn("preflight", section.lower())
        self.assertNotIn("just that table", section)

    def test_the_agent_description_promises_the_whole_report(self) -> None:
        agent = (REPO_ROOT / AGENT_PATH).read_text(encoding="utf-8")
        description = re.search(r"^description:\s*(.+)$", agent, re.MULTILINE).group(1)
        self.assertIn("in full", description)
        self.assertNotIn("just the phase table", description)


class EighthReviewRegressionTests(unittest.TestCase):
    """What a hand-written reader owes a real YAML parser.

    It is not one, so it has to refuse what it cannot resolve the same way: a
    repeated key (we take the first, PyYAML takes the last, strict parsers
    reject), a scalar where a mapping belongs, an empty list that looks like a
    value, a path that only resolves in a checkout.
    """

    def _mutate(self, old: str, new: str, path: str = HOSTS_DOCUMENT):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / path
        text = document.read_text(encoding="utf-8")
        self.assertIn(old, text)
        document.write_text(text.replace(old, new, 1), encoding="utf-8")
        return root

    def test_a_repeated_field_in_a_section_is_rejected(self) -> None:
        root = self._mutate(
            "      matcher: startup|resume|clear|compact\n      verified: true",
            "      matcher: startup|resume|clear|compact\n      verified: true\n      verified: false",
        )
        self.assertTrue(any("repeats" in e for e in validate_host_dialects(root)))

    def test_a_field_repeated_across_sections_is_allowed(self) -> None:
        """`path` legitimately appears in both agent and hook."""
        self.assertEqual(validate_host_dialects(REPO_ROOT), [])

    def test_an_empty_capability_list_is_rejected(self) -> None:
        """`[]` looks like a value and disabled the checks keyed on it."""
        for field, value in (("modes", "[binary, single, multi]"), ("choices", "[2, 4]")):
            with self.subTest(field=field):
                root = self._mutate(f"      {field}: {value}", f"      {field}: []")
                self.assertTrue(
                    any("empty list" in e for e in validate_host_dialects(root)),
                )

    def test_inherited_tools_may_still_record_an_empty_list(self) -> None:
        """The one list that legitimately names nothing."""
        self.assertIn("tool_names: []", (REPO_ROOT / HOSTS_DOCUMENT).read_text(encoding="utf-8"))
        self.assertEqual(validate_host_dialects(REPO_ROOT), [])

    def test_a_scalar_hosts_header_yields_no_records(self) -> None:
        """`hosts: nonsense` is a scalar; the records under it are not valid YAML."""
        root = self._mutate("\nhosts:\n", "\nhosts: nonsense\n")
        self.assertEqual(host_records(root), {})
        self.assertTrue(validate_host_dialects(root))

    def test_a_recorded_path_may_not_escape_the_plugin_root(self) -> None:
        """A traversal resolves in this checkout and finds nothing when installed."""
        for value, needle in (("../x/agents/", "escapes"), ("/tmp/agents/", "absolute")):
            with self.subTest(path=value):
                root = self._mutate("      path: agents/\n", f"      path: {value}\n")
                self.assertTrue(
                    any(needle in e for e in validate_host_dialects(root)),
                )

    def test_a_protocol_row_must_name_its_own_host(self) -> None:
        """Matching the tool alone let a row be relabelled to another host."""
        root = self._mutate(
            "| Claude Code | `AskUserQuestion`",
            "| OpenCode | `AskUserQuestion`",
            QUESTION_PROTOCOL_DOCUMENT,
        )
        self.assertTrue(
            any("no table row pairing" in e for e in validate_question_protocol(root)),
        )

    def test_every_hook_manifest_runs_the_shared_implementation(self) -> None:
        """The matcher says when it fires; this says what fires.

        Without it an adapter can carry the right matcher and run something else,
        becoming a second behavioural authority by omission.
        """
        manifest = "hooks/hooks.json"
        for label, mutate in (
            ("replaced", lambda p: p["hooks"]["SessionStart"][0].__setitem__(
                "hooks", [{"type": "command", "command": "echo unrelated"}])),
            ("removed", lambda p: p["hooks"]["SessionStart"][0].pop("hooks")),
        ):
            with self.subTest(callback=label), tempfile.TemporaryDirectory() as directory:
                root = build_root(directory)
                path = root / manifest
                payload = json.loads(path.read_text(encoding="utf-8"))
                mutate(payload)
                path.write_text(json.dumps(payload), encoding="utf-8")
                errors = validate_host_dialects(root)
                self.assertTrue(
                    any("invoke" in e or "declares no hooks" in e for e in errors), errors
                )


class QuestionProtocolTests(unittest.TestCase):
    def test_a_granted_tool_the_protocol_never_names_is_rejected(self) -> None:
        """The state this repository was actually in: a grant with no consumer.

        Three commands declared AskUserQuestion and validate.py pinned the
        string, while nothing ever told the agent to use it.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / QUESTION_PROTOCOL_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace("AskUserQuestion", "SomeOtherTool"),
                encoding="utf-8",
            )
            self.assertTrue(
                any("never says when to use it" in error for error in validate_question_protocol(root)),
            )

    def test_dropping_the_text_fallback_is_rejected(self) -> None:
        """Without it the rule silently means "skip the question" off Claude."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / QUESTION_PROTOCOL_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "Other — enter a custom response", "just pick one"
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("custom response" in error for error in validate_question_protocol(root)),
            )


if __name__ == "__main__":
    unittest.main()
