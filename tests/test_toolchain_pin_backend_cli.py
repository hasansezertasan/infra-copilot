"""The toolchain-pin step must tell the human to pin the state backend's CLI."""
from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REFERENCES = Path(__file__).resolve().parents[1] / '.ai-rulez/skills/infra/references'
# The preflight CLI checks in steps.yaml and the backend each one serves.
BACKEND_CLIS = {'s3': 'awscli', 'gcs': 'gcloud', 'azurerm': 'azure-cli'}


class ToolchainPinBackendCliTests(unittest.TestCase):
    def setUp(self) -> None:
        manifest = (REFERENCES / 'steps.yaml').read_text(encoding='utf-8')
        self.step = manifest.split('  - id: toolchain-pin\n', 1)[1].split('\n  - id: ', 1)[0]

    def test_step_names_every_backend_cli_and_the_plain_string_rule(self) -> None:
        for backend, tool in BACKEND_CLIS.items():
            self.assertIn(tool, self.step, f'{backend} backend CLI {tool} is not mentioned')
        self.assertIn('plain string under [tools]', self.step)
        self.assertIn('Do not use mise use', self.step)

    def test_each_backend_lists_its_own_cli_versions(self) -> None:
        # One fixed command would show AWS versions to a gcs or azurerm repository, and a
        # $STATE_BACKEND dispatch would make this generic step backend-dependent.
        self.assertNotIn('STATE_BACKEND', self.step)
        for tool in BACKEND_CLIS.values():
            self.assertEqual(self.step.count(f'mise ls-remote {tool} | tail -3'), 1, tool)

    def test_every_cli_the_preflight_requires_has_a_setup_row(self) -> None:
        setup = (REFERENCES / 'docs/setup.md').read_text(encoding='utf-8')
        for tool in BACKEND_CLIS.values():
            self.assertRegex(setup, rf'\|\s*`{re.escape(tool)}`\s*\|\s*`{re.escape(tool)}`\s*\|')

    def test_preflight_pins_exist_for_every_backend_cli(self) -> None:
        manifest = (REFERENCES / 'steps.yaml').read_text(encoding='utf-8')
        for tool in BACKEND_CLIS.values():
            self.assertIn(f'pin: mise.toml#tools.{tool}', manifest)

    def test_completion_check_requires_the_rendered_backend_cli_pin(self) -> None:
        # A committed mise.toml without the CLI must not satisfy the step, or a resumed
        # scan skips the HUMAN handoff and preflight fails later.
        clauses = re.findall(r"^      (\{ ! grep -Eqs 'backend\[\[:space:\]\]\+\"(\w+)\"'.*\} &&)$", self.step, re.M)
        self.assertEqual({backend for _, backend in clauses}, set(BACKEND_CLIS))
        script = 'pinned=$PINNED\n' + '\n'.join(clause.removesuffix(' &&') for clause, _ in clauses)
        for backend, tool in BACKEND_CLIS.items():
            for pinned, expected in (('terraform\ngh', 1), (f'terraform\n{tool}', 0)):
                with tempfile.TemporaryDirectory() as repo:
                    leaf = Path(repo, 'terraform/a')
                    leaf.mkdir(parents=True)
                    (leaf / 'backend.tf').write_text(f'terraform {{\n  backend "{backend}" {{}}\n}}\n')
                    result = subprocess.run(
                        ['sh', '-c', script.replace('\n{', ' &&\n{')], cwd=repo,
                        env={'PINNED': pinned, 'PATH': '/usr/bin:/bin'}, check=False,
                    )
                    self.assertEqual(result.returncode, expected, f'{backend} with pins {pinned!r}')


if __name__ == '__main__':
    unittest.main()
