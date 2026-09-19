"""The subagent and hook sections of hosts.md, and the artifacts they govern.

`hosts.md` owns the per-host record; `validate_host_contract` gates its question
tool rows, and this covers the two sections added for #19 and #42. What can be
gated is that a row marked shipped has its artifact in that host's dialect, and
that a row marked unshipped has no artifact at all.

Every case below is a failure that actually happened while establishing those
rows, not a hypothetical. Both dialects fail *silently* when wrong -- Antigravity
reported "agents: 1 processed" for an agent in Claude's comma-string form and
then never listed it in `agy agent` -- which is why the parity gate exists.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate import (
    AGENT_STEM,
    _canonical,
    PROTOCOL_DOCUMENTS,
    expected_hook_command,
    HOSTS_DOCUMENT,
    dialect_rows,
    validate_host_dialects,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = f"agents/{AGENT_STEM}.md"
HOOK_PATH = "hooks/hooks.json"
FIXTURE_PATHS = (
    HOSTS_DOCUMENT,
    AGENT_PATH,
    HOOK_PATH,
    "hooks/session-start.sh",
    # The delegation rule lives here and is asserted alongside the artifacts, so a
    # fixture without it is not a repository this validator can judge.
    *PROTOCOL_DOCUMENTS,
)


def build_root(directory: str) -> Path:
    root = Path(directory)
    for relative in FIXTURE_PATHS:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / relative, destination)
    return root


class RecordTests(unittest.TestCase):
    def test_the_repository_matches_its_own_record(self) -> None:
        self.assertEqual(validate_host_dialects(REPO_ROOT), [])

    def test_both_sections_are_readable(self) -> None:
        self.assertTrue(dialect_rows(REPO_ROOT, "## Subagent manifests"))
        self.assertTrue(dialect_rows(REPO_ROOT, "## Hook discovery"))

    def test_no_directory_is_claimed_by_two_shipped_rows(self) -> None:
        """Uniqueness is per directory, not global.

        Claude and Antigravity collide at root agents/, but .codex/agents/ and
        .opencode/agents/ are independent -- asserting one shipped row globally
        made those rows impossible to graduate.
        """
        rows = dialect_rows(REPO_ROOT, "## Subagent manifests")
        shipped = [r for r in rows if r["Shipped"].strip("* ").lower() == "yes"]
        directories = [r["Discovery path"].strip("`") for r in shipped]
        self.assertEqual(len(directories), len(set(directories)), directories)


class AgentTests(unittest.TestCase):
    def _root(self, old: str, new: str, path: str = HOSTS_DOCUMENT) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / path
        text = document.read_text(encoding="utf-8")
        self.assertIn(old, text)
        document.write_text(text.replace(old, new, 1), encoding="utf-8")
        return root

    def test_a_foreign_dialect_in_the_shipped_slot_is_rejected(self) -> None:
        """The silent failure the whole record exists for, in both directions.

        `claude plugin details` showed "Agents (1)" for an Antigravity-dialect
        file at root agents/ -- an agent whose whole tool grant is names Claude
        does not have.
        """
        root = self._root(
            "tools: Read, Bash, Glob, Grep, Skill",
            "tools:\n  - view_file\n  - grep_search\n  - run_command",
            AGENT_PATH,
        )
        self.assertTrue(validate_host_dialects(root))

    def test_the_grant_is_read_from_frontmatter_not_the_document(self) -> None:
        """A whole-file search let the frontmatter grant `Write` while the
        expected line sat in the prose below it."""
        root = self._root("tools: Read, Bash, Glob, Grep, Skill", "tools: Write", AGENT_PATH)
        document = root / AGENT_PATH
        document.write_text(
            document.read_text(encoding="utf-8")
            + "\n\nFor reference: tools: Read, Bash, Glob, Grep, Skill\n",
            encoding="utf-8",
        )
        self.assertTrue(validate_host_dialects(root))

    def test_the_declared_name_is_parsed_not_searched(self) -> None:
        """A substring test passed `name: wrong-agent`, because the stem still
        appeared in the heading and the instructions."""
        root = self._root(f"name: {AGENT_STEM}", "name: wrong-agent", AGENT_PATH)
        self.assertTrue(validate_host_dialects(root))

    def test_a_write_tool_in_the_record_is_rejected(self) -> None:
        root = self._root("`Grep`, `Skill` |", "`Grep`, `Skill`, `Write` |")
        self.assertTrue(any("Write" in e for e in validate_host_dialects(root)))

    def test_the_tools_the_instructions_need_are_required(self) -> None:
        """It loads the runbook through the skill tool and runs shell checks."""
        for tool, old, new in (
            ("Skill", ", `Skill` |", " |"),
            ("Bash", "`Bash`, ", ""),
        ):
            with self.subTest(tool=tool):
                root = self._root(old, new)
                self.assertTrue(validate_host_dialects(root))

    def test_an_agent_that_restates_the_scan_is_rejected(self) -> None:
        root = self._root("status.md", "my own inlined procedure", AGENT_PATH)
        self.assertTrue(
            any("status.md" in e for e in validate_host_dialects(root)),
            "removing the runbook must be reported",
        )

    def test_a_repo_relative_runbook_path_is_rejected(self) -> None:
        """The agent's working directory is the CONSUMING repository, while the
        runbooks ship in the plugin payload."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / AGENT_PATH
        document.write_text(
            document.read_text(encoding="utf-8")
            + "\nAlso read skills/infra-copilot/references/status.md directly.\n",
            encoding="utf-8",
        )
        self.assertTrue(
            any("consuming repository" in e for e in validate_host_dialects(root))
        )

    def test_the_manifest_stays_an_adapter(self) -> None:
        """The runbook owns scope, guardrails and the report contract."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / AGENT_PATH
        document.write_text(
            document.read_text(encoding="utf-8") + "\n" * 45, encoding="utf-8"
        )
        self.assertTrue(any("adapter" in e for e in validate_host_dialects(root)))

    def test_wiring_at_an_unshipped_path_is_rejected(self) -> None:
        """Codex records `.codex/agents/` and ships nothing there."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        shipped = root / ".codex/agents"
        shipped.mkdir(parents=True)
        (shipped / f"{AGENT_STEM}.toml").write_text('name = "x"\n', encoding="utf-8")
        self.assertTrue(any(".codex/agents" in e for e in validate_host_dialects(root)))

    def test_the_shared_directory_is_not_reported_twice(self) -> None:
        """Antigravity's unshipped path IS Claude's shipped one; reporting it
        would make the documented collision unshippable rather than recorded."""
        self.assertEqual(validate_host_dialects(REPO_ROOT), [])

    def test_the_record_can_revoke_the_agent(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        (root / AGENT_PATH).unlink()
        document = root / HOSTS_DOCUMENT
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "`Grep`, `Skill` | `Task` | **yes** |",
                "`Grep`, `Skill` | `Task` | no — withdrawn |",
                1,
            ),
            encoding="utf-8",
        )
        self.assertEqual(validate_host_dialects(root), [])

    def test_a_shipped_row_still_requires_its_manifest(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        (root / AGENT_PATH).unlink()
        self.assertTrue(any("no manifest is here" in e for e in validate_host_dialects(root)))


    def test_a_second_host_may_ship_at_an_independent_path(self) -> None:
        """Graduating OpenCode at .opencode/agents/ must not trip the collision
        rule, which exists only for the shared root agents/ directory.

        OpenCode rather than Codex: the inherited-tools dialect cannot express
        the read-only grant, so it is unshippable for a different reason.
        """
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / HOSTS_DOCUMENT
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "| `read`, `grep`, `glob`, `bash` | not recorded | no — not exercised |",
                "| `read`, `grep`, `glob`, `bash`, `skill` | `question` | **yes** |",
                1,
            ),
            encoding="utf-8",
        )
        shipped = root / ".opencode/agents"
        shipped.mkdir(parents=True)
        (shipped / f"{AGENT_STEM}.md").write_text(
            '---\nname: infra-auditor\ndescription: "Read-only scan."\n'
            "mode: subagent\ntools:\n  read: true\n  grep: true\n  glob: true\n"
            "  bash: true\n  skill: true\n---\n"
            "Invoke the `infra-copilot` skill, then follow status.md.\n",
            encoding="utf-8",
        )
        self.assertEqual(validate_host_dialects(root), [])

    def test_two_rows_may_not_ship_the_same_directory(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / HOSTS_DOCUMENT
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "`run_command` | not recorded | no — path collision |", "`run_command` | `Task` | **yes** |", 1
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("only one may" in e for e in validate_host_dialects(root)))

    def test_an_unrecorded_manifest_in_the_directory_is_rejected(self) -> None:
        """The host discovers the whole directory, not the recorded filename.

        `agents/rogue.md` carrying `tools: Write` passed: an agent nobody
        reviewed, with whatever grant it declares.
        """
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        (root / "agents/rogue.md").write_text(
            "---\nname: rogue\ntools: Write\n---\nrogue\n", encoding="utf-8"
        )
        self.assertTrue(any("rogue.md" in e for e in validate_host_dialects(root)))


class HookTests(unittest.TestCase):
    def _payload_root(self, mutate) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        path = root / HOOK_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        mutate(payload)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return root

    def test_a_contradicting_matcher_is_rejected(self) -> None:
        """A manifest with the wrong matcher is discovered and never fires."""
        root = self._payload_root(
            lambda p: p["hooks"]["SessionStart"][0].__setitem__("matcher", "nope")
        )
        self.assertTrue(any("matcher" in e for e in validate_host_dialects(root)))

    def test_a_sibling_of_hooks_is_rejected(self) -> None:
        """Antigravity counted a `_comment` beside `hooks` as a second hook."""
        root = self._payload_root(lambda p: p.__setitem__("_comment", ["why"]))
        self.assertTrue(validate_host_dialects(root))

    def test_naming_the_script_is_not_running_it(self) -> None:
        """`echo hooks/session-start.sh` passed a substring test."""
        root = self._payload_root(
            lambda p: p["hooks"]["SessionStart"][0].__setitem__(
                "hooks", [{"type": "command", "command": "echo hooks/session-start.sh"}]
            )
        )
        self.assertTrue(validate_host_dialects(root))

    def test_an_entry_with_no_callback_is_rejected(self) -> None:
        root = self._payload_root(lambda p: p["hooks"]["SessionStart"][0].pop("hooks"))
        self.assertTrue(
            validate_host_dialects(root)
        )

    def test_the_shipped_command_counts_as_an_invocation(self) -> None:
        """It resolves the path into a variable before running it, so the path
        and the shell cannot be required adjacent."""
        self.assertEqual(validate_host_dialects(REPO_ROOT), [])

    def test_a_sibling_hook_event_is_rejected(self) -> None:
        """Only SessionStart is recorded.

        A sibling such as PreToolUse would run behaviour on tool use that no
        capability record authorises and the shared implementation never sees.
        """
        root = self._payload_root(
            lambda p: p["hooks"].__setitem__(
                "PreToolUse",
                [{"matcher": "*", "hooks": [{"type": "command", "command": "echo x"}]}],
            )
        )
        self.assertTrue(validate_host_dialects(root))

    def test_a_manifest_at_an_unshipped_path_is_rejected(self) -> None:
        """Codex fired no hook from any candidate path; shipping one back fails."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        (root / "hooks/hooks-codex.json").write_text("{}", encoding="utf-8")
        self.assertTrue(
            any("hooks-codex.json" in e for e in validate_host_dialects(root))
        )

    def test_a_shipped_row_requires_its_manifest(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        (root / HOOK_PATH).unlink()
        self.assertTrue(any("no manifest is here" in e for e in validate_host_dialects(root)))


class MalformedRecordTests(unittest.TestCase):
    """A record that is wrong in shape must be reported, not crash or be trusted."""

    def _root(self, old: str, new: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / HOSTS_DOCUMENT
        text = document.read_text(encoding="utf-8")
        self.assertIn(old, text)
        document.write_text(text.replace(old, new, 1), encoding="utf-8")
        return root

    def test_a_short_row_is_reported_not_raised(self) -> None:
        """`| yes |` entered the shipped list and then indexed off the end,
        raising IndexError before the missing-column diagnostic could run."""
        root = self._root(
            "| OpenCode | `.opencode/agents/` | bool map | `read`, `grep`, `glob`, `bash` | not recorded | no — not exercised |",
            "| yes |",
        )
        self.assertTrue(any("cells, not" in e for e in validate_host_dialects(root)))

    def test_a_hook_path_may_not_escape_the_plugin_root(self) -> None:
        """Containment was applied to agent paths only, so a hook row of
        `../escape.json` had the validator read and accept an off-tree file."""
        root = self._root("| Claude Code | `hooks/hooks.json` |", "| Claude Code | `../escape.json` |")
        (root.parent / "escape.json").write_text("{}", encoding="utf-8")
        self.assertTrue(any("escapes" in e for e in validate_host_dialects(root)))

    def test_an_echo_prefixed_command_does_not_count(self) -> None:
        """`echo sh hooks/session-start.sh` satisfied "path present and shell
        token present" while executing only `echo`."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        path = root / HOOK_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["hooks"]["SessionStart"][0]["hooks"] = [
            {"type": "command", "command": "echo sh hooks/session-start.sh"}
        ]
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertTrue(validate_host_dialects(root))

    def test_a_callback_that_is_not_a_command_is_rejected(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        path = root / HOOK_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["hooks"]["SessionStart"][0]["hooks"][0]["type"] = "prompt"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertTrue(validate_host_dialects(root))


class CoverageAndGrantTests(unittest.TestCase):
    """A row a host would act on must exist, be unambiguous, and be reachable."""

    def _root(self, old: str, new: str, path: str = HOSTS_DOCUMENT) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / path
        text = document.read_text(encoding="utf-8")
        self.assertIn(old, text)
        document.write_text(text.replace(old, new, 1), encoding="utf-8")
        return root

    def test_both_sections_cover_every_recorded_host(self) -> None:
        """The protocol sends a run to its own host's row, so a missing row
        leaves that run with no delegation or hook decision at all."""
        root = self._root(
            "| Codex CLI | `.codex/agents/` | none — session tools are inherited | — | not recorded | no — not exercised |\n",
            "",
        )
        self.assertTrue(
            any("not the recorded hosts" in e for e in validate_host_dialects(root))
        )

    def test_a_duplicate_name_field_is_rejected(self) -> None:
        """Duplicate YAML keys are ambiguous: a first-match read saw the right
        name while the host could register the wrong one, or none."""
        root = self._root(
            f"name: {AGENT_STEM}", f"name: {AGENT_STEM}\nname: wrong-agent", AGENT_PATH
        )
        self.assertTrue(
            any("name" in e for e in validate_host_dialects(root)),
            "a duplicate name must be reported",
        )

    def test_a_negated_instruction_is_not_delegation(self) -> None:
        """"Never invoke `infra-copilot` or `status.md`" carried both names and
        told every delegated run not to load the canonical workflow."""
        root = self._root(
            "Invoke the `infra-copilot` skill, then follow its `references/` links to\n"
            "`status.md`, `protocol.md`, and `steps.yaml`.",
            "Never invoke `infra-copilot` or `status.md`.",
            AGENT_PATH,
        )
        self.assertTrue(
            any("no instruction to invoke" in e for e in validate_host_dialects(root))
        )

    def test_an_unshipped_directory_is_enumerated_too(self) -> None:
        """The host discovers the directory, shipped or not."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        rogue = root / ".codex/agents"
        rogue.mkdir(parents=True)
        (rogue / "rogue.toml").write_text('name = "rogue"\n', encoding="utf-8")
        self.assertTrue(any("rogue.toml" in e for e in validate_host_dialects(root)))

    def test_required_tools_use_each_dialect_spelling(self) -> None:
        """OpenCode's native grant is lowercase, so one global Claude-cased pair
        made that row unsatisfiable however it was written."""
        root = self._root(
            "| OpenCode | `.opencode/agents/` | bool map | `read`, `grep`, `glob`, `bash` | not recorded | no — not exercised |",
            "| OpenCode | `.opencode/agents/` | bool map | `read`, `grep`, `glob`, `bash`, `skill` | `question` | **yes** |",
        )
        shipped = root / ".opencode/agents"
        shipped.mkdir(parents=True)
        (shipped / f"{AGENT_STEM}.md").write_text(
            "---\nname: infra-auditor\ndescription: \"Read-only scan.\"\n"
            "mode: subagent\ntools:\n  read: true\n"
            "  grep: true\n  glob: true\n  bash: true\n  skill: true\n---\n"
            "Invoke the `infra-copilot` skill, then follow status.md.\n",
            encoding="utf-8",
        )
        self.assertEqual(validate_host_dialects(root), [])

    def test_the_shell_must_receive_the_script(self) -> None:
        """`x=hooks/session-start.sh; sh -c true` mentions the path and runs a
        shell, and does neither thing together."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        path = root / HOOK_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["hooks"]["SessionStart"][0]["hooks"] = [
            {"type": "command", "command": "x=hooks/session-start.sh; sh -c true"}
        ]
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertTrue(validate_host_dialects(root))

    def test_a_non_string_command_is_reported_not_raised(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        path = root / HOOK_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["hooks"]["SessionStart"][0]["hooks"] = [
            {"type": "command", "command": 123}
        ]
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertTrue(validate_host_dialects(root))


class AmbiguityTests(unittest.TestCase):
    """A record or manifest that says two things must not be read as saying one."""

    def _root(self, old: str, new: str, path: str = HOSTS_DOCUMENT) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / path
        text = document.read_text(encoding="utf-8")
        self.assertIn(old, text)
        document.write_text(text.replace(old, new, 1), encoding="utf-8")
        return root

    def test_a_negated_imperative_is_not_a_directive(self) -> None:
        """"Never Invoke the infra-copilot skill" matched the imperative."""
        for phrase in (
            "Never Invoke the `infra-copilot` skill, nor follow",
            "Do not Invoke the `infra-copilot` skill, nor follow",
        ):
            with self.subTest(phrase=phrase):
                root = self._root(
                    "Invoke the `infra-copilot` skill, then follow", phrase, AGENT_PATH
                )
                self.assertTrue(
                    any("no instruction to invoke" in e for e in validate_host_dialects(root))
                )

    def test_duplicate_toml_names_are_rejected(self) -> None:
        """A duplicate key makes the document invalid TOML, so the host registers
        nothing -- while a first-match read saw the right name."""
        root = self._root(
            "| `.codex/agents/` | none — session tools are inherited | — | not recorded | no — not exercised |",
            "| `.codex/agents/` | none — session tools are inherited | — | `codex_task` | **yes** |",
        )
        shipped = root / ".codex/agents"
        shipped.mkdir(parents=True)
        (shipped / f"{AGENT_STEM}.toml").write_text(
            'name = "infra-auditor"\nname = "wrong-agent"\n'
            'developer_instructions = """Invoke the infra-copilot skill, then follow status.md."""\n',
            encoding="utf-8",
        )
        self.assertTrue(
            any("not valid TOML" in e for e in validate_host_dialects(root)),
            "a duplicate key makes the document unparseable, which is the real failure",
        )

    def test_a_repeated_capability_heading_is_rejected(self) -> None:
        """A second table was ignored while a reader sees two competing records."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / HOSTS_DOCUMENT
        document.write_text(
            document.read_text(encoding="utf-8")
            + "\n## Subagent manifests (second)\n\n| Host | A | B | C | D |\n"
            "|---|---|---|---|---|\n| Claude Code | `nowhere/` | comma string | `Write` | **yes** |\n",
            encoding="utf-8",
        )
        self.assertTrue(any("occurs 2 times" in e for e in validate_host_dialects(root)))


class HookCommandTests(unittest.TestCase):
    """Every command spelling ten review rounds produced, kept as evidence.

    These used to exercise a shell walker directly. The walker is gone: the
    callback is now compared byte-for-byte against a command rendered from the
    host record, so each of these fails as "not equal" rather than by a rule of
    its own. They are retained because they are the corpus that showed modelling
    shell was the wrong tool -- if a future change reintroduces analysis, this
    list is what it has to survive.
    """

    REJECTED = (
        ("mention only", "echo sh hooks/session-start.sh"),
        ("shell runs something else", "x=hooks/session-start.sh; sh -c true"),
        ("child shell echoes it", """s=hooks/session-start.sh; sh -c 'echo "$s"'"""),
        ("reassigned", 's=hooks/session-start.sh; s=/bin/true; sh "$s"'),
        ("a different file", "sh hooks/session-start.sh.bak"),
        ("outside the payload", "sh /tmp/hooks/session-start.sh"),
        ("bare relative", "sh hooks/session-start.sh"),
        ("unreachable after exit", 'exit 0; sh "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"'),
        ("guarded by &&", 'false && sh "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"'),
        ("exec replaces the shell", 'exec /bin/true; sh "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"'),
        ("exit guarded by a non-test", 'false || exit 0; sh "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"'),
        ("&& exit after a test",
         's="${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"; [ -f "$s" ] && exit 0; sh "$s"'),
        ("inverted guard",
         's="${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"; [ ! -f "$s" ] || exit 0; sh "$s"'),
        ("guard whose success blocks the run",
         's="${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"; [ -z "$s" ] || exit 0; sh "$s"'),
        ("guarded exec runs a command",
         's="${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"; [ -f "$s" ] || exec touch /tmp/x; sh "$s"'),
        ("adapter-owned trailing command",
         'sh "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"; touch /tmp/x'),
        ("redirection discards the announcement",
         'r="${CLAUDE_PLUGIN_ROOT:-}"; s="${r%/}/hooks/session-start.sh"; sh "$s" >/dev/null'),
        ("command substitution",
         'x="$(touch /tmp/x)"; sh "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"'),
        ("backtick substitution", 'x=`id`; sh "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"'),
        ("unterminated quote", 'sh "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh'),
        ("trim removes a path component", 'sh "${CLAUDE_PLUGIN_ROOT%/*}/hooks/session-start.sh"'),
        ("prefix trim", 'sh "${CLAUDE_PLUGIN_ROOT##*/}/hooks/session-start.sh"'),
        ("foreign root variable",
         'r="${CODEX_PLUGIN_ROOT:-}"; [ -n "$r" ] || exit 0; '
         's="${r%/}/hooks/session-start.sh"; [ -f "$s" ] || exit 0; sh "$s"'),
        ("assignment that alters command lookup",
         'PATH=/definitely-missing; r="${CLAUDE_PLUGIN_ROOT:-}"; '
         's="${r%/}/hooks/session-start.sh"; sh "$s"'),
        ("two invocations",
         'sh "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"; '
         'sh "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"'),
    )

    def _with_command(self, command: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        path = root / HOOK_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["hooks"]["SessionStart"][0]["hooks"][0]["command"] = command
        path.write_text(json.dumps(payload), encoding="utf-8")
        return root

    def test_rejected_forms(self) -> None:
        for label, command in self.REJECTED:
            with self.subTest(form=label):
                self.assertTrue(
                    validate_host_dialects(self._with_command(command)), command
                )

    def test_the_shipped_command_is_what_the_record_renders(self) -> None:
        """The accepted form is one value, not a family, so there is exactly one
        thing to assert."""
        shipped = json.loads((REPO_ROOT / HOOK_PATH).read_text(encoding="utf-8"))
        command = shipped["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        self.assertEqual(command, expected_hook_command("CLAUDE_PLUGIN_ROOT"))
        self.assertEqual(validate_host_dialects(REPO_ROOT), [])


class DialectAndShapeTests(unittest.TestCase):
    """Per-host spellings, exact affirmatives, and shapes that used to crash."""

    def _root(self, old: str, new: str, path: str = HOSTS_DOCUMENT) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / path
        text = document.read_text(encoding="utf-8")
        self.assertIn(old, text)
        document.write_text(text.replace(old, new, 1), encoding="utf-8")
        return root

    def test_forbidden_tools_use_each_dialect_spelling(self) -> None:
        """One Claude-cased tuple let OpenCode's lowercase `write` through,
        handing a read-only auditor a direct write capability."""
        root = self._root(
            "| OpenCode | `.opencode/agents/` | bool map | `read`, `grep`, `glob`, `bash` | not recorded | no — not exercised |",
            "| OpenCode | `.opencode/agents/` | bool map | `read`, `grep`, `glob`, `bash`, `skill`, `write` | `question` | **yes** |",
        )
        shipped = root / ".opencode/agents"
        shipped.mkdir(parents=True)
        (shipped / f"{AGENT_STEM}.md").write_text(
            "---\nname: infra-auditor\ndescription: \"Read-only scan.\"\n"
            "mode: subagent\ntools:\n  read: true\n"
            "  grep: true\n  glob: true\n  bash: true\n  skill: true\n  write: true\n"
            "---\nInvoke the `infra-copilot` skill, then follow status.md.\n",
            encoding="utf-8",
        )
        self.assertTrue(any("write" in e for e in validate_host_dialects(root)))

    def test_a_negated_runbook_directive_is_rejected(self) -> None:
        """"then do not follow status.md" named the runbook and skipped it."""
        root = self._root(
            "Invoke the `infra-copilot` skill, then follow its `references/` links to\n"
            "`status.md`, `protocol.md`, and `steps.yaml`.",
            "Invoke the `infra-copilot` skill, then do not follow `status.md`.",
            AGENT_PATH,
        )
        self.assertTrue(
            any("un-negated instruction" in e for e in validate_host_dialects(root))
        )

    def test_a_negator_on_a_previous_line_does_not_disqualify(self) -> None:
        """The clause bound matters: the shipped manifest's own heading reads
        "Load it by name, not by path" directly above the imperative."""
        self.assertEqual(validate_host_dialects(REPO_ROOT), [])

    def test_a_shipped_cell_must_be_the_exact_affirmative(self) -> None:
        """`yes — withdrawn` read as shipped, so a trailing comment could turn a
        refusal into a capability claim."""
        root = self._root("`Grep`, `Skill` | `Task` | **yes** |", "`Grep`, `Skill` | `Task` | yes — withdrawn |")
        self.assertTrue(
            any("neither 'yes' nor a refusal" in e for e in validate_host_dialects(root))
        )

    def test_a_non_list_sessionstart_is_reported_not_raised(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        path = root / HOOK_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["hooks"]["SessionStart"] = None
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertTrue(validate_host_dialects(root))


class ShapeTests(unittest.TestCase):
    """Containers and documents that are valid JSON or Markdown but wrong."""

    def test_equivalent_paths_are_one_directory(self) -> None:
        """`agents/` and `./agents/` are the same discovery directory, and keying
        ownership by the raw spelling let two rows own it while each looked
        unique."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / HOSTS_DOCUMENT
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "| Antigravity | `agents/` | YAML list | `view_file`, `grep_search`, "
                "`find_by_name`, `run_command` | not recorded | no — path collision |",
                "| Antigravity | `./agents/` | comma string | `Read`, `Bash`, `Glob`, "
                "`Grep`, `Skill` | `Task` | **yes** |",
                1,
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("only one may" in e for e in validate_host_dialects(root)))

    def test_a_non_list_nested_hooks_is_reported_not_raised(self) -> None:
        """The outer container was checked and the nested one was not."""
        for value in (1, True, "x"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = build_root(directory)
                path = root / HOOK_PATH
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["hooks"]["SessionStart"][0]["hooks"] = value
                path.write_text(json.dumps(payload), encoding="utf-8")
                self.assertTrue(
                    validate_host_dialects(root)
                )

    def test_malformed_frontmatter_is_rejected(self) -> None:
        """The host parses the whole document before it discovers the agent, so
        one bad field removes it while the protocol keeps delegating."""
        for label, replacement in (
            ("unclosed flow sequence", 'description: [\nbroken: "x"'),
            ("unbalanced quote", 'description: "oops\n'),
        ):
            with self.subTest(defect=label), tempfile.TemporaryDirectory() as directory:
                root = build_root(directory)
                document = root / AGENT_PATH
                document.write_text(
                    document.read_text(encoding="utf-8").replace(
                        'description: "Read-only', replacement + '\nold: "Read-only', 1
                    ),
                    encoding="utf-8",
                )
                self.assertTrue(
                    validate_host_dialects(root)
                )

    def test_the_shipped_frontmatter_is_well_formed(self) -> None:
        self.assertEqual(validate_host_dialects(REPO_ROOT), [])


class DirectiveAndFrontmatterTests(unittest.TestCase):
    """The last places a mention was accepted as an instruction, or a malformed
    document as a valid one."""

    def _agent(self, old: str, new: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / AGENT_PATH
        text = document.read_text(encoding="utf-8")
        self.assertIn(old, text)
        document.write_text(text.replace(old, new, 1), encoding="utf-8")
        return root

    def test_a_descriptive_mention_is_not_a_directive(self) -> None:
        """"The file status.md exists" named the runbook and instructed nothing."""
        root = self._agent(
            "Invoke the `infra-copilot` skill, then follow its `references/` links to\n"
            "`status.md`, `protocol.md`, and `steps.yaml`.",
            "Invoke the `infra-copilot` skill. The file `status.md` exists.",
        )
        self.assertTrue(
            any("un-negated instruction" in e for e in validate_host_dialects(root))
        )

    def test_frontmatter_is_held_to_a_fixed_shape(self) -> None:
        """A balance check passed `description: [foo,,bar]`; the contract is three
        known keys, so the shape is checkable exactly without a YAML parser."""
        for label, replacement in (
            ("flow collection", "description: [foo,,bar]"),
            ("unknown key", 'extra: "x"'),
        ):
            with self.subTest(defect=label):
                root = self._agent('description: "Read-only', replacement + '\nold: "Read-only')
                self.assertTrue(
                    validate_host_dialects(root)
                )

    def test_a_missing_required_key_is_rejected(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / AGENT_PATH
        lines = [
            line
            for line in document.read_text(encoding="utf-8").splitlines(keepends=True)
            if not line.startswith("description:")
        ]
        document.write_text("".join(lines), encoding="utf-8")
        self.assertTrue(
            validate_host_dialects(root)
        )

    def test_delegation_requires_both_gates(self) -> None:
        """A shipped row says the agent exists, never that this session can reach
        it -- hosts gate tools per session, so a denied Task must fall back inline
        rather than fail the scan."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        for relative in PROTOCOL_DOCUMENTS:
            document = root / relative
            document.write_text(
                document.read_text(encoding="utf-8").replace("currently declared", "pigs fly"),
                encoding="utf-8",
            )
        self.assertTrue(
            any("delegation rule is missing" in e for e in validate_host_dialects(root))
        )


class RecordedValueTests(unittest.TestCase):
    """Columns added because the gate was trusting things the table never said."""

    def _root(self, old: str, new: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / HOSTS_DOCUMENT
        text = document.read_text(encoding="utf-8")
        self.assertIn(old, text)
        document.write_text(text.replace(old, new, 1), encoding="utf-8")
        return root

    def test_a_manifest_may_only_use_its_own_root_variable(self) -> None:
        """Claude reading CODEX_PLUGIN_ROOT finds nothing, exits before running
        the script, and the announcement disappears with no error to notice."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        manifest = root / HOOK_PATH
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                "CLAUDE_PLUGIN_ROOT", "CODEX_PLUGIN_ROOT"
            ),
            encoding="utf-8",
        )
        self.assertTrue(
            validate_host_dialects(root)
        )

    def test_an_extra_cell_is_rejected(self) -> None:
        """`row[-1]` read the extra cell while a reader saw the named column, so
        the gate and the document disagreed about the same host."""
        root = self._root("| `Task` | **yes** |", "| `Task` | no — not exercised | **yes** |")
        self.assertTrue(any("cells, not" in e for e in validate_host_dialects(root)))

    def test_a_shipped_row_must_record_an_invocation_tool(self) -> None:
        """The delegation gate checks that tool is available; without one there is
        nothing to check."""
        root = self._root("| `Task` | **yes** |", "| not recorded | **yes** |")
        self.assertTrue(
            any("no invocation tool" in e for e in validate_host_dialects(root))
        )

    def test_an_opencode_manifest_must_stay_a_subagent(self) -> None:
        """`mode: primary` registers a primary agent, not the subagent the
        protocol invokes."""
        root = self._root(
            "| `read`, `grep`, `glob`, `bash` | not recorded | no — not exercised |",
            "| `read`, `grep`, `glob`, `bash`, `skill` | `question` | **yes** |",
        )
        shipped = root / ".opencode/agents"
        shipped.mkdir(parents=True)
        (shipped / f"{AGENT_STEM}.md").write_text(
            '---\nname: infra-auditor\ndescription: "Scan."\nmode: primary\n'
            "tools:\n  read: true\n  grep: true\n  glob: true\n  bash: true\n"
            "  skill: true\n---\nInvoke the `infra-copilot` skill, then follow status.md.\n",
            encoding="utf-8",
        )
        self.assertTrue(validate_host_dialects(root))

    def test_a_toml_manifest_is_parsed(self) -> None:
        """tomllib is stdlib, so unlike YAML there is no dependency to weigh -- and
        a parse rejects every malformed construct at once."""
        row = "| Codex CLI | `.codex/agents/` | none — session tools are inherited | — | not recorded | no — not exercised |"
        shipped_row = "| Codex CLI | `.codex/agents/` | none — session tools are inherited | — | `codex_task` | **yes** |"
        for label, body, expect_clean in (
            ("unterminated", 'name = "infra-auditor"\nbroken = [\n', False),
            ("duplicate key", 'name = "infra-auditor"\nname = "wrong"\n', False),
            (
                "valid",
                'name = "infra-auditor"\ndeveloper_instructions = """Invoke the '
                'infra-copilot skill, then follow status.md."""\n',
                True,
            ),
        ):
            with self.subTest(document=label):
                root = self._root(row, shipped_row)
                shipped = root / ".codex/agents"
                shipped.mkdir(parents=True)
                (shipped / f"{AGENT_STEM}.toml").write_text(body, encoding="utf-8")
                errors = validate_host_dialects(root)
                # The row is unshippable regardless -- inherited tools cannot
                # express the grant -- so this asserts only the parse verdict.
                parse_errors = [e for e in errors if "not valid TOML" in e]
                if expect_clean:
                    self.assertEqual(parse_errors, [], errors)
                else:
                    self.assertTrue(parse_errors, errors)

    def test_the_protocol_names_no_host_specific_tool(self) -> None:
        """It reads the Invocation tool column instead, the way the decision rule
        reads the question tool."""
        for relative in PROTOCOL_DOCUMENTS:
            with self.subTest(document=relative):
                self.assertNotIn("Task", (REPO_ROOT / relative).read_text(encoding="utf-8"))


class RootedAndBodyTests(unittest.TestCase):
    """Where the command runs from, and where the instructions have to live."""

    def _hook(self, command: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        path = root / HOOK_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["hooks"]["SessionStart"][0]["hooks"] = [
            {"type": "command", "command": command}
        ]
        path.write_text(json.dumps(payload), encoding="utf-8")
        return root

    def test_a_bare_relative_operand_is_rejected(self) -> None:
        """The hook runs with the *consuming* repository as its directory, so a
        relative path runs a consumer-owned script or nothing."""
        root = self._hook("sh hooks/session-start.sh")
        self.assertTrue(validate_host_dialects(root))

    def test_duplicate_sessionstart_entries_are_rejected(self) -> None:
        """A set collapsed them and each copy passed independently, so the host
        registered the command twice and announced twice."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        path = root / HOOK_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["hooks"]["SessionStart"].append(
            json.loads(json.dumps(payload["hooks"]["SessionStart"][0]))
        )
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertTrue(
            validate_host_dialects(root)
        )

    def test_directives_must_be_in_the_body(self) -> None:
        """Frontmatter is discovery metadata, not the agent's instructions, so a
        description carrying both directives over a body of "Do nothing." is an
        agent that is never told to do anything."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        (root / AGENT_PATH).write_text(
            "---\nname: infra-auditor\n"
            'description: "Invoke the infra-copilot skill and follow status.md."\n'
            "tools: Read, Bash, Glob, Grep, Skill\n---\n\nDo nothing.\n",
            encoding="utf-8",
        )
        self.assertTrue(
            any("no instruction to invoke" in e for e in validate_host_dialects(root))
        )

    def test_an_invalid_yaml_escape_is_rejected(self) -> None:
        """`\\q` is not a YAML escape, so the host parses nothing and discovers
        no agent while the protocol keeps delegating."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / AGENT_PATH
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                'description: "Read-only', 'description: "Bad \\q Read-only', 1
            ),
            encoding="utf-8",
        )
        self.assertTrue(
            validate_host_dialects(root)
        )


class SixthRoundTests(unittest.TestCase):
    """Duplicates, malformed headers, and directives read from the wrong place."""

    CODEX_ROW = (
        "| Codex CLI | `.codex/agents/` | none — session tools are inherited | — "
        "| not recorded | no — not exercised |"
    )
    CODEX_SHIPPED = (
        "| Codex CLI | `.codex/agents/` | none — session tools are inherited | — "
        "| `codex_task` | **yes** |"
    )

    def _root(self, old: str = "", new: str = "") -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        if old:
            document = root / HOSTS_DOCUMENT
            text = document.read_text(encoding="utf-8")
            self.assertIn(old, text)
            document.write_text(text.replace(old, new, 1), encoding="utf-8")
        return root

    def test_toml_directives_come_from_the_instruction_field(self) -> None:
        """A comment carried them while `developer_instructions = "Do nothing."`
        was what the host would load."""
        root = self._root(self.CODEX_ROW, self.CODEX_SHIPPED)
        shipped = root / ".codex/agents"
        shipped.mkdir(parents=True)
        (shipped / f"{AGENT_STEM}.toml").write_text(
            "# Invoke the infra-copilot skill, then follow status.md.\n"
            'name = "infra-auditor"\ndeveloper_instructions = "Do nothing."\n',
            encoding="utf-8",
        )
        self.assertTrue(
            any("no instruction to invoke" in e for e in validate_host_dialects(root))
        )

    def test_parent_segments_collapse(self) -> None:
        self.assertEqual(_canonical("agents/../agents/"), _canonical("agents/"))

    def test_a_duplicate_callback_is_rejected(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        path = root / HOOK_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        entry = payload["hooks"]["SessionStart"][0]
        entry["hooks"].append(json.loads(json.dumps(entry["hooks"][0])))
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertTrue(
            validate_host_dialects(root),
            "one announcement is the contract, so a second callback is rejected "
            "whether or not it is identical",
        )

    def test_a_malformed_numeric_escape_is_rejected(self) -> None:
        """YAML fixes the payload width: \\x takes two hex digits, not any two
        characters."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / AGENT_PATH
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                'description: "Read-only', 'description: "Bad \\xZZ Read-only', 1
            ),
            encoding="utf-8",
        )
        self.assertTrue(validate_host_dialects(root))

    def test_a_negated_delegation_gate_is_rejected(self) -> None:
        """"never declared or allowed" contains every noun and inverts the rule."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        for relative in PROTOCOL_DOCUMENTS:
            document = root / relative
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "is currently declared", "is never declared"
                ),
                encoding="utf-8",
            )
        self.assertTrue(
            any("delegation rule is missing" in e for e in validate_host_dialects(root))
        )

    def test_a_mistyped_header_is_reported_not_raised(self) -> None:
        root = self._root("| Shipped |", "| Shippd |")
        self.assertTrue(
            any("declares columns" in e for e in validate_host_dialects(root))
        )


class HeaderCardinalityTests(unittest.TestCase):
    def test_a_repeated_column_is_rejected(self) -> None:
        """A set comparison passed a second `Shipped` column, and dict(zip(...))
        then kept the later cell -- so the value a reader sees under the named
        column and the one every rule read were different cells.
        """
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / HOSTS_DOCUMENT
        lines = []
        for line in document.read_text(encoding="utf-8").splitlines(keepends=True):
            stripped = line.strip()
            if stripped.startswith("| Host | Discovery path"):
                lines.append(line.rstrip("\n").rstrip("|") + "| Shipped |\n")
            elif stripped.startswith("|---|---|---|---|---|---|"):
                lines.append("|---|---|---|---|---|---|---|\n")
            elif re.match(r"\| (Claude Code|Antigravity|Codex CLI|OpenCode) \| `", stripped):
                lines.append(line.rstrip("\n").rstrip("|") + "| **yes** |\n")
            else:
                lines.append(line)
        document.write_text("".join(lines), encoding="utf-8")
        self.assertTrue(
            any("repeats the column" in e for e in validate_host_dialects(root))
        )


class SeventhRoundTests(unittest.TestCase):
    """Shapes that survived the previous round's boundaries."""

    def _root(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return build_root(directory.name)

    def test_an_indented_line_outside_tools_is_rejected(self) -> None:
        """`tools` is the only structured field this contract has, so indentation
        anywhere else is invalid YAML and the host discovers no agent."""
        root = self._root()
        document = root / AGENT_PATH
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "name: infra-auditor", "name: infra-auditor\n  garbage: true", 1
            ),
            encoding="utf-8",
        )
        self.assertTrue(validate_host_dialects(root))

    def test_a_second_callback_is_rejected_however_it_differs(self) -> None:
        """One announcement is the contract; two callbacks differing only by name
        both run."""
        root = self._root()
        path = root / HOOK_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        entry = payload["hooks"]["SessionStart"][0]
        extra = json.loads(json.dumps(entry["hooks"][0]))
        extra["name"] = "another"
        entry["hooks"].append(extra)
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertTrue(validate_host_dialects(root))

    def test_any_relative_runbook_path_is_rejected(self) -> None:
        """`references/status.md` resolves into the consumer exactly as the longer
        spelling does."""
        root = self._root()
        document = root / AGENT_PATH
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "`status.md`, `protocol.md`, and `steps.yaml`.", "`references/status.md`.", 1
            ),
            encoding="utf-8",
        )
        self.assertTrue(
            any("relative runbook path" in e for e in validate_host_dialects(root))
        )

    def test_a_non_string_matcher_is_rejected(self) -> None:
        """str() erased the type, so a numeric matcher compared equal to its
        textual spelling."""
        for value in (123, None, True):
            with self.subTest(matcher=value):
                root = self._root()
                path = root / HOOK_PATH
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["hooks"]["SessionStart"][0]["matcher"] = value
                path.write_text(json.dumps(payload), encoding="utf-8")
                self.assertTrue(
                    validate_host_dialects(root)
                )

    def test_a_dialect_without_a_skill_loader_cannot_ship(self) -> None:
        """The manifest's first instruction is to load the runbook by name, and
        no tool in the YAML-list grant can do it."""
        root = self._root()
        document = root / HOSTS_DOCUMENT
        document.write_text(
            document.read_text(encoding="utf-8")
            .replace("| Antigravity | `agents/` | YAML list |", "| Antigravity | `elsewhere/` | YAML list |", 1)
            .replace(
                "`run_command` | not recorded | no — path collision |",
                "`run_command` | `agy_task` | **yes** |",
                1,
            ),
            encoding="utf-8",
        )
        shipped = root / "elsewhere"
        shipped.mkdir()
        (shipped / f"{AGENT_STEM}.md").write_text(
            '---\nname: infra-auditor\ndescription: "Scan."\ntools:\n  - view_file\n'
            "  - grep_search\n  - find_by_name\n  - run_command\n---\n"
            "Invoke the `infra-copilot` skill, then follow status.md.\n",
            encoding="utf-8",
        )
        self.assertTrue(
            any("cannot express the grant" in e for e in validate_host_dialects(root))
        )


class EighthRoundTests(unittest.TestCase):
    """Budgets and duplicates the previous round's shapes still allowed."""

    def _root(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return build_root(directory.name)

    def test_an_unterminated_single_quote_is_rejected(self) -> None:
        """Only double quotes were balanced, and the name comparison stripped the
        stray one -- while a YAML parser rejects the document."""
        root = self._root()
        document = root / AGENT_PATH
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "name: infra-auditor", "name: 'infra-auditor", 1
            ),
            encoding="utf-8",
        )
        self.assertTrue(validate_host_dialects(root))

    def test_the_adapter_budget_bounds_size_not_just_lines(self) -> None:
        """`agents/` is outside the Markdown line-length lint, so thousands of
        words on one physical line kept the line count green."""
        root = self._root()
        document = root / AGENT_PATH
        document.write_text(
            document.read_text(encoding="utf-8") + "\nLong. " + ("workflow " * 3000) + "\n",
            encoding="utf-8",
        )
        self.assertTrue(any("characters >" in e for e in validate_host_dialects(root)))

    def test_a_repeated_delegation_section_is_rejected(self) -> None:
        """The agent reads the whole protocol, so a second copy could contradict
        the first while only the first was validated."""
        root = self._root()
        for relative in PROTOCOL_DOCUMENTS:
            document = root / relative
            document.write_text(
                document.read_text(encoding="utf-8")
                + "\n## Later\n\n### Running the scan in an isolated context\n\n"
                "Never delegate.\n",
                encoding="utf-8",
            )
        self.assertTrue(any("occurs 2 times" in e for e in validate_host_dialects(root)))


class NinthRoundTests(unittest.TestCase):
    def _root(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return build_root(directory.name)

    def test_the_whole_name_scalar_is_compared(self) -> None:
        """YAML reads `name: infra-auditor garbage` as one value, while a
        first-token capture saw the right name."""
        root = self._root()
        document = root / AGENT_PATH
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "name: infra-auditor", "name: infra-auditor garbage", 1
            ),
            encoding="utf-8",
        )
        self.assertTrue(
            validate_host_dialects(root)
        )

    def test_the_availability_gate_must_be_affirmative(self) -> None:
        """Requiring `declared` alone let "declared but denied" satisfy the gate
        it exists to enforce."""
        root = self._root()
        for relative in PROTOCOL_DOCUMENTS:
            document = root / relative
            document.write_text(
                document.read_text(encoding="utf-8").replace("and allowed", "but denied"),
                encoding="utf-8",
            )
        self.assertTrue(
            any("delegation rule is missing" in e for e in validate_host_dialects(root))
        )

    def test_the_readme_cites_the_record_rather_than_copying_it(self) -> None:
        """hosts.md is the single capability record; prose repeating it is a
        second copy nothing keeps in step when a host graduates."""
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("skills/infra-copilot/references/hosts.md", readme)
        for copied in ("hooks-codex.json", "experimental flag", "root `hooks.json`"):
            self.assertNotIn(copied, readme)


class TenthRoundTests(unittest.TestCase):
    def _root(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return build_root(directory.name)

    def test_a_doubled_quote_name_is_rejected(self) -> None:
        """YAML reads `''infra-auditor''` as the literal `'infra-auditor'`, while
        an even quote count and strip() both saw the expected stem."""
        root = self._root()
        document = root / AGENT_PATH
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "name: infra-auditor", "name: ''infra-auditor''", 1
            ),
            encoding="utf-8",
        )
        self.assertTrue(
            validate_host_dialects(root)
        )

    def test_an_inherited_tools_dialect_cannot_ship(self) -> None:
        """Session tools are inherited, so the read-only grant the protocol
        promises can be neither expressed nor checked."""
        root = self._root()
        document = root / HOSTS_DOCUMENT
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "| — | not recorded | no — not exercised |", "| — | `codex_task` | **yes** |", 1
            ),
            encoding="utf-8",
        )
        shipped = root / ".codex/agents"
        shipped.mkdir(parents=True)
        (shipped / f"{AGENT_STEM}.toml").write_text(
            'name = "infra-auditor"\ndeveloper_instructions = """Invoke the '
            'infra-copilot skill, then follow status.md."""\n',
            encoding="utf-8",
        )
        self.assertTrue(
            any("cannot express the grant" in e for e in validate_host_dialects(root))
        )

    def test_the_status_only_boundary_is_part_of_the_rule(self) -> None:
        """Without it an action run could delegate, and the status runbook
        substitutes away the current-checkout checks resumption needs."""
        root = self._root()
        for relative in PROTOCOL_DOCUMENTS:
            document = root / relative
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "**`status` and only `status`**", "**any skill**"
                ),
                encoding="utf-8",
            )
        self.assertTrue(
            any("delegation rule is missing" in e for e in validate_host_dialects(root))
        )


class CrossArtifactTests(unittest.TestCase):
    """The record has to agree with the adapters that consume it.

    These are the checks the render-and-compare refactor kept: unlike shell or
    YAML shape, agreement between two files is not derivable from either one.
    """

    def _root(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return build_root(directory.name)

    def test_the_invocation_tool_must_be_granted_to_the_status_command(self) -> None:
        """Renaming the capability here while `allowed-tools` lists the old one
        leaves /infra-status silently falling back to an inline scan."""
        root = self._root()
        document = root / HOSTS_DOCUMENT
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "| `Task` | **yes** |", "| `Dispatch` | **yes** |", 1
            ),
            encoding="utf-8",
        )
        self.assertTrue(
            any("would not be permitted" in e for e in validate_host_dialects(root))
        )

    def test_a_shipped_root_must_be_handled_by_the_shared_script(self) -> None:
        """The record and the manifest can agree on a variable session-start.sh
        does not test, and the hook then emits another host's output shape."""
        root = self._root()
        document = root / HOSTS_DOCUMENT
        manifest = root / HOOK_PATH
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "`CLAUDE_PLUGIN_ROOT`", "`NEW_PLUGIN_ROOT`", 1
            ),
            encoding="utf-8",
        )
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                "CLAUDE_PLUGIN_ROOT", "NEW_PLUGIN_ROOT"
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("does not test" in e for e in validate_host_dialects(root)))

    def test_delegation_requires_the_row_to_be_marked_shipped(self) -> None:
        """"records a subagent" is true of unshipped rows too, so the gate has to
        name the shipped state or an absent agent can be called."""
        root = self._root()
        for relative in PROTOCOL_DOCUMENTS:
            document = root / relative
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "delegate only where that row is marked shipped",
                    "delegate wherever a row exists",
                ),
                encoding="utf-8",
            )
        self.assertTrue(
            any("delegation rule is missing" in e for e in validate_host_dialects(root))
        )


if __name__ == "__main__":
    unittest.main()
