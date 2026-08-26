from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.validate import (
    JSON_MANIFESTS,
    collect_manifest_errors,
    validate_config_fallbacks,
    validate_json_manifests,
    validate_links,
    validate_manifest_paths,
    validate_phase_five_rule,
    validate_toolchain_contract,
    validate_tool_pins,
)


class ValidateLinksTests(unittest.TestCase):
    def test_rejects_link_that_resolves_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            repository = workspace / "repo"
            docs = repository / "docs"
            docs.mkdir(parents=True)
            (workspace / "outside.md").write_text("outside", encoding="utf-8")
            (docs / "guide.md").write_text(
                "[outside](../../outside.md)", encoding="utf-8"
            )

            self.assertEqual(
                validate_links(repository),
                [
                    "docs/guide.md: link '../../outside.md' resolves outside the "
                    "repository"
                ],
            )

    def test_accepts_existing_link_inside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            docs = repository / "docs"
            docs.mkdir()
            (repository / "README.md").write_text("read me", encoding="utf-8")
            (docs / "guide.md").write_text(
                "[read me](../README.md)", encoding="utf-8"
            )

            self.assertEqual(validate_links(repository), [])


class ValidateConfigFallbacksTests(unittest.TestCase):
    def test_canonical_entrypoints_document_legacy_fallback(self) -> None:
        self.assertEqual(validate_config_fallbacks(), [])


class ValidatePhaseFiveRuleTests(unittest.TestCase):
    def test_status_skill_requires_empty_import_set(self) -> None:
        self.assertEqual(validate_phase_five_rule(), [])

    def test_rejects_rule_that_accepts_a_clean_run_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            document = repository / ".ai-rulez/skills/status/SKILL.md"
            document.parent.mkdir(parents=True)
            document.write_text(
                "Infer done from the workspace's latest HCP run being clean.",
                encoding="utf-8",
            )

            self.assertEqual(
                validate_phase_five_rule(repository),
                [
                    ".ai-rulez/skills/status/SKILL.md: phase-5 completion rule "
                    "missing 'imports: 0'",
                    ".ai-rulez/skills/status/SKILL.md: phase-5 completion rule "
                    "missing 'incomplete'",
                    ".ai-rulez/skills/status/SKILL.md: phase-5 completion rule "
                    "missing 'status `applied`'",
                ],
            )


class ValidateReleaseSurfacesTests(unittest.TestCase):
    def test_json_manifests_parse(self) -> None:
        self.assertEqual(validate_json_manifests(), [])

    def test_manifest_paths_stay_inside_repository(self) -> None:
        self.assertEqual(validate_manifest_paths(), [])

    def test_workflow_and_documentation_tool_pins_match(self) -> None:
        self.assertEqual(validate_tool_pins(), [])

    def test_malformed_manifest_is_reported_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            for relative in JSON_MANIFESTS:
                manifest = repository / relative
                manifest.parent.mkdir(parents=True, exist_ok=True)
                manifest.write_text("{}", encoding="utf-8")
            (repository / ".claude-plugin/marketplace.json").write_text(
                "{not json", encoding="utf-8"
            )

            # Path validation indexes into these manifests, so reaching it with
            # `{}` would raise KeyError and this call would never return.
            errors = collect_manifest_errors(repository)

        self.assertTrue(
            any(
                error.startswith(".claude-plugin/marketplace.json: invalid JSON")
                for error in errors
            ),
            errors,
        )


class ValidateToolchainContractTests(unittest.TestCase):
    def test_committed_pins_flow_to_hcp(self) -> None:
        self.assertEqual(validate_toolchain_contract(), [])

    def test_rejects_active_mise_state_and_unlocked_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            steps = repository / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
            hcp = repository / ".ai-rulez/skills/infra-copilot/references/hcp.md"
            setup = (
                repository
                / ".ai-rulez/skills/infra-copilot/references/docs/setup.md"
            )
            import_guide = (
                repository
                / ".ai-rulez/skills/infra-copilot/references/docs/import.md"
            )
            config = (
                repository
                / ".ai-rulez/skills/infra-copilot/references/config.md"
            )
            status = repository / ".ai-rulez/skills/status/SKILL.md"
            setup.parent.mkdir(parents=True)
            status.parent.mkdir(parents=True)
            steps.write_text("pin=$(mise current terraform)", encoding="utf-8")
            hcp.write_text("terraform-version", encoding="utf-8")
            setup.write_text("mise trust mise.toml", encoding="utf-8")
            import_guide.write_text("", encoding="utf-8")
            config.write_text(
                "export TERRAFORM_VERSION=$(mise config get)", encoding="utf-8"
            )
            status.write_text("", encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(any("active mise state" in error for error in errors), errors)
        self.assertTrue(
            any("MISE_LOCKED=1 mise install" in error for error in errors), errors
        )
        self.assertTrue(
            any("review must precede trust" in error for error in errors), errors
        )
        self.assertTrue(any("MISE_LOCKED=1" in error for error in errors), errors)
        self.assertTrue(any("before preflight" in error for error in errors), errors)
        self.assertTrue(any("without pin state" in error for error in errors), errors)

    def test_rejects_unlocked_conditional_tools_and_unactivated_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            references = repository / ".ai-rulez/skills/infra-copilot/references"
            steps = references / "steps.yaml"
            hcp = references / "hcp.md"
            setup = references / "docs/setup.md"
            import_guide = references / "docs/import.md"
            config = references / "config.md"
            status = repository / ".ai-rulez/skills/status/SKILL.md"
            setup.parent.mkdir(parents=True)
            status.parent.mkdir(parents=True)
            # A fixed tool list leaves conditionally configured tools unvalidated.
            steps.write_text(
                "MISE_LOCKED=1 mise install --dry-run terraform gh jq", encoding="utf-8"
            )
            hcp.write_text("terraform-version", encoding="utf-8")
            # Installs the toolchain but never activates it or uses `mise exec`.
            setup.write_text(
                "cat -- mise.toml\nmise trust mise.toml\ntouch mise.lock\n"
                "mise lock\nMISE_LOCKED=1 mise install\n",
                encoding="utf-8",
            )
            # Installs cf-terraforming as it writes the pin, before the lock exists.
            import_guide.write_text(
                "mise use --path mise.toml github:cloudflare/cf-terraforming@0.27.0\n"
                "mise lock\ngit add mise.toml mise.lock\n",
                encoding="utf-8",
            )
            config.write_text("", encoding="utf-8")
            status.write_text("", encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(
            any("enumerate the committed tool list" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("must be activated" in error for error in errors), errors
        )
        self.assertTrue(
            any("installs the pin before locking" in error for error in errors), errors
        )

    # The manifest's `check` snippets are POSIX shell by contract, and this test
    # proves them by executing them against shell fixtures. Windows has no
    # /bin/sh, so the assertion is unrunnable there rather than failing.
    @unittest.skipUnless(os.name == "posix", "manifest checks are POSIX shell")
    def test_tool_checks_reject_non_exact_selectors(self) -> None:
        steps = (
            Path(__file__).parents[1]
            / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
        ).read_text(encoding="utf-8")

        def check_for(tool: str) -> str:
            match = re.search(
                rf"  - tool: {tool}\n(?:(?!  - tool:).*\n)*?    check: >-\n"
                rf"(?P<body>(?:      [^\n]*\n)+)",
                steps,
                re.MULTILINE,
            )
            self.assertIsNotNone(match)
            return "\n".join(
                line[6:] for line in match.group("body").splitlines()
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            binary_directory = Path(temporary_directory)
            scripts = {
                "mise": """#!/bin/sh
if [ "$1" = config ]; then printf '%s\n' "$PIN"; else exit 0; fi
""",
                "terraform": """#!/bin/sh
printf '%s\n' '{"terraform_version":"1.15.9"}'
""",
                "gh": """#!/bin/sh
printf '%s\n' 'gh version 2.81.0 (fixture)'
""",
                "jq": """#!/bin/sh
if [ "$1" = --version ]; then printf '%s\n' 'jq-1.8.1';
else cat >/dev/null; printf '%s\n' '1.15.9'; fi
""",
            }
            for name, body in scripts.items():
                executable = binary_directory / name
                executable.write_text(body, encoding="utf-8")
                executable.chmod(0o755)

            environment = os.environ | {
                "PATH": f"{binary_directory}:/usr/bin:/bin",
            }
            exact = {"terraform": "1.15.9", "gh": "2.81.0", "jq": "1.8.1"}
            for tool, version in exact.items():
                command = check_for(tool)
                passing = subprocess.run(
                    ["/bin/sh", "-c", command],
                    env=environment | {"PIN": version},
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                self.assertEqual(passing.returncode, 0, tool)
                for selector in ("latest", ">=1.9", "1.15"):
                    rejected = subprocess.run(
                        ["/bin/sh", "-c", command],
                        env=environment | {"PIN": selector},
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    self.assertNotEqual(rejected.returncode, 0, (tool, selector))


    # Executed against shell fixtures, so POSIX-only for the same reason as above.
    @unittest.skipUnless(os.name == "posix", "manifest checks are POSIX shell")
    def test_lock_check_covers_every_configured_tool(self) -> None:
        """The locked dry-run must cover conditionally added tools, not a fixed set."""
        steps = (
            Path(__file__).parents[1]
            / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
        ).read_text(encoding="utf-8")
        match = re.search(
            r"  - tool: mise\n    check: >-\n(?P<body>(?:      [^\n]*\n)+)", steps
        )
        self.assertIsNotNone(match)
        check = " ".join(
            line[6:] for line in match.group("body").splitlines()
        )

        # `mise install` here stands in for the real locked install: it fails for any
        # requested tool absent from LOCKED, exactly as --locked fails for a tool with
        # no lockfile entry for the current platform.
        fixture_mise = """#!/bin/sh
case "$1" in
  --version) exit 0 ;;
  config) sed -n '/^\\[tools\\]/,$p' ./mise.toml | sed '1d' ;;
  install)
    shift 2
    for requested in "$@"; do
      found=1
      for locked in $LOCKED; do
        [ "$requested" = "$locked" ] && found=0
      done
      [ "$found" = 0 ] || exit 1
    done
    ;;
esac
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            binaries = repository / "bin"
            binaries.mkdir()
            executable = binaries / "mise"
            executable.write_text(fixture_mise, encoding="utf-8")
            executable.chmod(0o755)
            # gcloud is the conditional pin: configured, but absent from the lock.
            (repository / "mise.toml").write_text(
                '[tools]\nterraform = "1.15.9"\ngh = "2.81.0"\njq = "1.8.1"\n'
                'gcloud = "551.0.0"\n',
                encoding="utf-8",
            )
            (repository / "mise.lock").write_text("# @generated\n", encoding="utf-8")
            # A contributor's global config (commit.gpgsign, core.hooksPath, a
            # gpg.format) would otherwise fail these commits and error the test for
            # a reason unrelated to the contract under test.
            git = os.environ | {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull,
            }
            for command in (
                ["git", "init", "-q"],
                ["git", "add", "mise.toml", "mise.lock"],
                [
                    "git",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=test",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-qm",
                    "pins",
                ],
            ):
                subprocess.run(command, cwd=repository, env=git, check=True)

            def run(locked: str) -> int:
                return subprocess.run(
                    ["/bin/sh", "-c", check],
                    cwd=repository,
                    env=os.environ
                    | {
                        "PATH": f"{binaries}:/usr/bin:/bin",
                        "LOCKED": locked,
                    },
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode

            # The old fixed list would have passed this: gcloud is configured but
            # has no lock data, so a fresh clone's locked install would fail.
            self.assertNotEqual(run("terraform gh jq"), 0)
            # Withhold the *first* key's lock data too, so a check that drops a tool
            # from either end of the enumerated list is caught.
            self.assertNotEqual(run("gh jq gcloud"), 0)
            self.assertEqual(run("terraform gh jq gcloud"), 0)

            # An unpinned repository must not pass on file presence alone.
            (repository / "mise.toml").write_text("[tools]\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=repository, env=git, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=test",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-qm",
                    "empty",
                ],
                cwd=repository,
                env=git,
                check=True,
            )
            self.assertNotEqual(run("terraform gh jq gcloud"), 0)


    # Needs a real jq, since the point of the assertion is which JSON field the
    # check asks for. POSIX-only for the same reason as the checks above.
    @unittest.skipUnless(os.name == "posix", "manifest checks are POSIX shell")
    def test_gcloud_check_reads_the_sdk_version_field(self) -> None:
        """`core` is a release date; the pin matches the Google Cloud SDK field."""
        jq = shutil.which("jq")
        if jq is None:
            self.skipTest("jq is required to exercise the gcloud check")
        steps = (
            Path(__file__).parents[1]
            / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
        ).read_text(encoding="utf-8")
        match = re.search(
            r"  - tool: gcloud\n(?:(?!  - tool:).*\n)*?    check: >-\n"
            r"(?P<body>(?:      [^\n]*\n)+)",
            steps,
        )
        self.assertIsNotNone(match)
        check = " ".join(line[6:] for line in match.group("body").splitlines())

        # Verbatim shape of `gcloud version --format=json` from SDK 551.0.0: the
        # component named `core` carries a release date, not the SDK version.
        fixture_gcloud = """#!/bin/sh
cat <<'JSON'
{
  "Google Cloud SDK": "551.0.0",
  "bq": "2.1.26",
  "core": "2026.01.02",
  "gcloud-crc32c": "1.0.0",
  "gsutil": "5.35"
}
JSON
"""
        fixture_mise = """#!/bin/sh
[ "$1" = config ] && printf '%s\\n' "$PIN"
exit 0
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            binaries = repository / "bin"
            binaries.mkdir()
            for name, body in (("gcloud", fixture_gcloud), ("mise", fixture_mise)):
                executable = binaries / name
                executable.write_text(body, encoding="utf-8")
                executable.chmod(0o755)
            (binaries / "jq").symlink_to(jq)

            def run(pin: str) -> int:
                return subprocess.run(
                    ["/bin/sh", "-c", check],
                    cwd=repository,
                    env=os.environ
                    | {"PATH": f"{binaries}:/usr/bin:/bin", "PIN": pin},
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode

            # Without terraform/gcp the pin is not yet required.
            self.assertEqual(run("551.0.0"), 0)

            (repository / "terraform/gcp").mkdir(parents=True)
            # The regression: matching pin and installed SDK must agree. Reading
            # `core.version` yielded an empty string and kept this red.
            self.assertEqual(run("551.0.0"), 0)
            # Drift, the release date mistaken for a version, and non-exact
            # selectors all have to fail.
            for pin in ("550.0.0", "2026.01.02", "latest", ">=551", "551"):
                self.assertNotEqual(run(pin), 0, pin)


if __name__ == "__main__":
    unittest.main()
