from __future__ import annotations

import os
import re
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


if __name__ == "__main__":
    unittest.main()
