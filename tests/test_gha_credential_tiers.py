"""Exercise secret-placement checks with safe, leaking, and missing inventories."""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REFERENCES = Path(__file__).resolve().parents[1] / '.ai-rulez/skills/infra-copilot/references'


@unittest.skipUnless(os.name == 'posix', 'credential checks require POSIX shell')
class CredentialTierTests(unittest.TestCase):
    def run_check(self, step_id: str, repo_names: list[str], env_names: list[str],
                  inventory: list[dict[str, object]] | None = None,
                  gate_status: int = 0) -> subprocess.CompletedProcess[str]:
        manifest = (REFERENCES / 'steps.yaml').read_text()
        block = manifest.split(f'  - id: {step_id}\n', 1)[1].split('\n  - id:', 1)[0]
        match = re.search(r'^    check: \|\n((?:      .*\n|\n)+)', block, re.M)
        self.assertIsNotNone(match)
        script = textwrap.dedent(match.group(1))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bin').mkdir()
            (root / 'checks').mkdir()
            (root / 'checks/gha-apply-gate.sh').write_text(f'exit {gate_status}\n')
            stub = root / 'bin/gh'
            stub.write_text('#!/bin/sh\ncase "$*" in\n'
                            '  *"--env production"*) printf "%s\\n" "$ENV_NAMES" ;;\n'
                            '  *) printf "%s\\n" "$REPO_NAMES" ;;\nesac\n')
            stub.chmod(0o755)
            (root / '.infra-copilot').mkdir()
            (root / '.infra-copilot/config.md').write_text('fixture\n')
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            subprocess.run(['git', 'add', '.'], cwd=root, check=True)
            subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                            'commit', '-qm', 'fixture'], cwd=root, check=True)
            return subprocess.run(['sh', '-c', script], cwd=root, capture_output=True, text=True,
                                  env={**os.environ, 'PATH': f'{root / "bin"}{os.pathsep}{os.environ["PATH"]}',
                                       'INFRA_COPILOT_REFERENCES': str(root), 'REPO': 'owner/repo',
                                       'REPO_NAMES': '\n'.join(repo_names), 'ENV_NAMES': '\n'.join(env_names),
                                       'NEW_PROVIDER_SECRETS': json.dumps(inventory or []),
                                       'NEW_PROVIDER_CREDENTIALS_VERIFIED_AT': datetime.datetime.now(
                                           datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')})

    def test_bootstrap_requires_read_repo_and_write_environment_only(self) -> None:
        cases = (
            ('cf-token-gha', ['CLOUDFLARE_API_TOKEN_READ'], ['CLOUDFLARE_API_TOKEN']),
            ('gh-app-gha', ['GH_APP_READ_ID', 'GH_APP_READ_INSTALLATION_ID', 'GH_APP_READ_PEM'],
             ['GH_APP_ID', 'GH_APP_INSTALLATION_ID', 'GH_APP_PEM']),
        )
        for step_id, read_names, write_names in cases:
            with self.subTest(step=step_id):
                self.assertEqual(self.run_check(step_id, read_names, write_names).returncode, 0)
                for leaked in write_names:
                    self.assertEqual(self.run_check(step_id, read_names + [leaked], write_names).returncode, 1)
                for missing in read_names:
                    self.assertEqual(self.run_check(step_id, [n for n in read_names if n != missing],
                                                    write_names).returncode, 1)
                self.assertEqual(self.run_check(step_id, read_names, []).returncode, 1)
                self.assertEqual(self.run_check(step_id, read_names, write_names, gate_status=2).returncode, 2)

    def test_additional_provider_scopes_and_optional_write_leaks(self) -> None:
        inventory = [{'name': 'READ_TOKEN', 'required': True, 'scope': 'plan'},
                     {'name': 'WRITE_TOKEN', 'required': True, 'scope': 'apply'},
                     {'name': 'OPTIONAL_WRITE', 'required': False, 'scope': 'apply'}]
        self.assertEqual(self.run_check('new-provider-secrets-gha', ['READ_TOKEN'], ['WRITE_TOKEN'],
                                        inventory).returncode, 0)
        for repo_names, env_names in ((['READ_TOKEN', 'WRITE_TOKEN'], ['WRITE_TOKEN']),
                                       (['READ_TOKEN', 'OPTIONAL_WRITE'], ['WRITE_TOKEN']),
                                       (['READ_TOKEN'], []), ([], ['READ_TOKEN', 'WRITE_TOKEN'])):
            with self.subTest(repo=repo_names, environment=env_names):
                self.assertEqual(self.run_check('new-provider-secrets-gha', repo_names, env_names,
                                                inventory).returncode, 1)
        for invalid in ([{'name': 'OLD_TOKEN', 'required': True}],
                        [{'name': 'TOKEN', 'required': True, 'scope': 'unknown'}],
                        inventory + [{'name': 'read_token', 'required': True, 'scope': 'apply'}]):
            self.assertEqual(self.run_check('new-provider-secrets-gha', ['READ_TOKEN'], ['WRITE_TOKEN'],
                                            invalid).returncode, 1)


if __name__ == '__main__':
    unittest.main()
