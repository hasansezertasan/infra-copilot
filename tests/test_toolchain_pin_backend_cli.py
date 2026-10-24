"""The toolchain-pin step must tell the human to pin the state backend's CLI."""
from __future__ import annotations

import re
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

    def test_every_cli_the_preflight_requires_has_a_setup_row(self) -> None:
        setup = (REFERENCES / 'docs/setup.md').read_text(encoding='utf-8')
        for tool in BACKEND_CLIS.values():
            self.assertRegex(setup, rf'\|\s*`{re.escape(tool)}`\s*\|\s*`{re.escape(tool)}`\s*\|')

    def test_preflight_pins_exist_for_every_backend_cli(self) -> None:
        manifest = (REFERENCES / 'steps.yaml').read_text(encoding='utf-8')
        for tool in BACKEND_CLIS.values():
            self.assertIn(f'pin: mise.toml#tools.{tool}', manifest)


if __name__ == '__main__':
    unittest.main()
