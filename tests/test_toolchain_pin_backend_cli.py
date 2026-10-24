"""The backend-cli-pin step must tell the human to pin the state backend's CLI."""
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
        self.step = manifest.split('  - id: backend-cli-pin\n', 1)[1].split('\n  - id: ', 1)[0]

    def test_step_names_every_backend_cli_and_the_plain_string_rule(self) -> None:
        for backend, tool in BACKEND_CLIS.items():
            self.assertIn(tool, self.step, f'{backend} backend CLI {tool} is not mentioned')
        self.assertIn('plain string under [tools]', self.step)
        for tool in BACKEND_CLIS.values():
            # Phase 6's inventory rejects an unclassified non-bootstrap pin.
            self.assertIn(f'`# infra-skills:general-tool {tool}`', self.step)
        self.assertIn('Do not use mise use', self.step)

    def test_each_backend_lists_its_own_cli_versions(self) -> None:
        # One fixed command would show AWS versions to a gcs or azurerm repository, and a
        # $STATE_BACKEND dispatch would make this generic step backend-dependent.
        self.assertNotIn('STATE_BACKEND', self.step.split('    check:', 1)[0])
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

    def test_completion_check_follows_the_validated_config(self) -> None:
        # A committed mise.toml without the CLI must not satisfy the step, or a resumed scan
        # skips the HUMAN handoff and preflight fails later. Routing is the validated service
        # inventory, so a mixed HCP repository with an object-storage leaf is covered too.
        check = re.search(r'    check: >-\n((?:      .*\n)+)', self.step + '\n').group(1)
        script = '\n'.join(line.strip() for line in check.splitlines())
        fake_mise = ('#!/bin/sh\n'
                     '[ "$1" = install ] && exit ${FAKE_INSTALL:-0}\n'
                     'key=${5#tools.}\n'
                     "sed -n \"s/^$key = \\\"\\(.*\\)\\\"$/\\1/p\" mise.toml\n")
        cases = [
            ({'HAS_OBJECT_STORAGE': 'false', 'STATE_BACKEND': ''}, {}, 0),
            ({'HAS_OBJECT_STORAGE': 'true', 'STATE_BACKEND': 'hcp'}, {}, 0),
            *[({'HAS_OBJECT_STORAGE': 'true', 'STATE_BACKEND': b}, {}, 1) for b in BACKEND_CLIS],
            *[({'HAS_OBJECT_STORAGE': 'true', 'STATE_BACKEND': b}, {tool: '1.2.3'}, 0)
              for b, tool in BACKEND_CLIS.items()],
            # A pin for another backend's CLI does not satisfy this one.
            ({'HAS_OBJECT_STORAGE': 'true', 'STATE_BACKEND': 's3'}, {'gcloud': '1.2.3'}, 1),
            # A pin that the lock cannot install (missing or stale lock entry) is not done.
            ({'HAS_OBJECT_STORAGE': 'true', 'STATE_BACKEND': 's3', 'FAKE_INSTALL': '1'}, {'awscli': '1.2.3'}, 1),
            # An inline table is not an exact pin.
            ({'HAS_OBJECT_STORAGE': 'true', 'STATE_BACKEND': 's3'}, {'awscli': '{ version = "1.2.3" }'}, 1),
        ]
        for env, pins, expected in cases:
            with self.subTest(env=env, pins=pins), tempfile.TemporaryDirectory() as repo, \
                    tempfile.TemporaryDirectory() as bindir:
                mise = Path(bindir, 'mise')
                mise.write_text(fake_mise)
                mise.chmod(0o755)
                lines = ['[tools]', 'terraform = "1.9.0"'] + [
                    f'{k} = {v}' if v.startswith('{') else f'{k} = "{v}"' for k, v in pins.items()]
                Path(repo, 'mise.toml').write_text('\n'.join(lines) + '\n')
                Path(repo, 'mise.lock').write_text('')
                for cmd in (['init', '-q'], ['add', '.'], ['-c', 'user.name=t', '-c', 'user.email=t@t',
                                                           'commit', '-qm', 'x']):
                    subprocess.run(['git', *cmd], cwd=repo, check=True, capture_output=True)
                result = subprocess.run(
                    ['sh', '-c', script], cwd=repo, check=False, capture_output=True,
                    env={**env, 'PATH': f'{bindir}:/usr/bin:/bin'},
                )
                self.assertEqual(result.returncode, expected, result.stderr.decode())


if __name__ == '__main__':
    unittest.main()
