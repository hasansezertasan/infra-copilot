"""Behavioural tests for the SessionStart hook.

The hook is the only shipped artifact that runs on *every* session in *every*
repository, whether or not the plugin is used, so its two silent paths matter
more than its output: an unrecognised repo and the kill switch must both emit
nothing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "hooks/session-start.sh"
MANIFEST = REPO_ROOT / "hooks/hooks.json"


@unittest.skipUnless(os.name == "posix", "the hook is a POSIX shell script")
class SessionHookTests(unittest.TestCase):
    def run_hook(self, *, marker: str | None, host_env: dict[str, str] | None = None,
                 disabled: bool = False) -> str:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            if marker == "config":
                (root / ".infra-copilot").mkdir()
                (root / ".infra-copilot/config.md").touch()
            elif marker == "legacy":
                (root / ".claude").mkdir()
                (root / ".claude/infra-copilot.local.md").touch()
            elif marker == "terraform":
                (root / "terraform").mkdir()
            env = {**os.environ, **(host_env or {})}
            for unset in ("CLAUDE_PLUGIN_ROOT", "CODEX_PLUGIN_ROOT",
                          "ANTIGRAVITY_PLUGIN_ROOT", "AGY_PLUGIN_ROOT"):
                if not (host_env or {}).get(unset):
                    env.pop(unset, None)
            if disabled:
                env["INFRA_COPILOT_HOOK_DISABLE"] = "1"
            else:
                env.pop("INFRA_COPILOT_HOOK_DISABLE", None)
            result = subprocess.run(
                ["sh", str(HOOK)], cwd=root, env=env, capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

    def test_says_nothing_in_an_unrelated_repository(self) -> None:
        """It runs in every session, so silence is the default it must get right."""
        self.assertEqual(json.loads(self.run_hook(marker=None)), {})

    def test_kill_switch_silences_it_even_when_the_repo_matches(self) -> None:
        output = self.run_hook(marker="config", disabled=True)
        self.assertEqual(json.loads(output), {})

    def test_each_marker_triggers_it(self) -> None:
        for marker in ("config", "legacy", "terraform"):
            with self.subTest(marker=marker):
                payload = json.loads(
                    self.run_hook(marker=marker, host_env={"CLAUDE_PLUGIN_ROOT": "/x"})
                )
                self.assertIn("hookSpecificOutput", payload)

    def test_host_output_shapes(self) -> None:
        for variable in ("CLAUDE_PLUGIN_ROOT", "CODEX_PLUGIN_ROOT",
                         "ANTIGRAVITY_PLUGIN_ROOT", "AGY_PLUGIN_ROOT"):
            with self.subTest(host=variable):
                payload = json.loads(
                    self.run_hook(marker="config", host_env={variable: "/x"})
                )
                self.assertEqual(
                    payload["hookSpecificOutput"]["hookEventName"], "SessionStart"
                )
        payload = json.loads(self.run_hook(marker="config"))
        self.assertIn("additional_context", payload, "unrecognised hosts take this shape")

    def test_context_never_claims_state(self) -> None:
        """A hook that reported a verdict would compete with the resume scan.

        A stale claim there is worse than no claim, so the text must route
        rather than assert.
        """
        payload = json.loads(
            self.run_hook(marker="config", host_env={"CLAUDE_PLUGIN_ROOT": "/x"})
        )
        context = payload["hookSpecificOutput"]["additionalContext"]
        # Word-bounded: an unbounded substring test matches "green" inside
        # "greenfield", which is a legitimate word here.
        for forbidden in ("phase", "green", "red", "passing", "failing"):
            with self.subTest(term=forbidden):
                self.assertIsNone(
                    re.search(rf"\b{forbidden}\b", context, re.IGNORECASE),
                    f"the hook must not report a verdict; found {forbidden!r}",
                )
        for symbol in ("✓", "✗"):
            self.assertNotIn(symbol, context)
        self.assertIn("never treat this message as authority", context.lower())

    def test_manifest_points_at_the_shipped_script(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        entry = manifest["hooks"]["SessionStart"][0]["hooks"][0]
        self.assertIn("hooks/session-start.sh", entry["command"])
        self.assertEqual(entry["type"], "command")
        self.assertLessEqual(entry["timeout"], 10, "it runs on every session start")

    def test_manifest_never_runs_a_script_from_the_working_directory(self) -> None:
        """A cwd fallback would execute a script out of whatever repo the user is in.

        CLAUDE_PLUGIN_ROOT is not guaranteed for every invocation, so the
        fallback has to be "do nothing", not "trust the checkout".
        """
        command = json.loads(MANIFEST.read_text(encoding="utf-8"))[
            "hooks"
        ]["SessionStart"][0]["hooks"][0]["command"]

        self.assertNotIn("./hooks", command)
        self.assertIn("CLAUDE_PLUGIN_ROOT", command)
        self.assertIn("exit 0", command, "unresolved root must exit, not fall back")

    def test_matcher_covers_every_session_start_source(self) -> None:
        """`claude --resume` reports source `resume`; omitting it skips the hook."""
        matcher = json.loads(MANIFEST.read_text(encoding="utf-8"))[
            "hooks"
        ]["SessionStart"][0]["matcher"]

        for source in ("startup", "resume", "clear", "compact"):
            self.assertIn(source, matcher)

    def test_context_does_not_name_a_marker_it_cannot_vouch_for(self) -> None:
        """Naming config.md is false for a repo matching only terraform/.

        That would be the hook injecting wrong repository state, which is what
        its own closing sentence warns against.
        """
        for marker in ("config", "legacy", "terraform"):
            with self.subTest(marker=marker):
                payload = json.loads(
                    self.run_hook(marker=marker, host_env={"CLAUDE_PLUGIN_ROOT": "/x"})
                )
                context = payload["hookSpecificOutput"]["additionalContext"]
                self.assertNotIn(".infra-copilot/config.md", context)
                self.assertNotIn("terraform/ tree", context)


if __name__ == "__main__":
    unittest.main()
