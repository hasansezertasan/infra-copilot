"""Keep GitHub App permission guidance aligned across setup paths."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / '.ai-rulez/skills/infra-copilot/references'


class GitHubAppPermissionTests(unittest.TestCase):
    def test_documentation_covers_environment_reads_and_membership_writes(self) -> None:
        expected = {
            'github.md': (
                '**Repository**: Administration (R/W), Actions (R), Contents (R), Metadata (R), Pull requests (R/W).',
                '**Organization**: Members (R/W), Administration (R/W).',
            ),
            'docs/secrets.md': (
                'Grant Repository Administration (read/write), Actions (read), Contents (read), Metadata (read), and Pull requests (read/write);',
                'Grant Organization Members (read/write) and Administration (read/write).',
            ),
            'docs/setup.md': (
                '- Repository: Administration (R/W), Actions (R), Contents (R), Metadata (R), Pull requests (R/W).',
                '- Organization: Members (R/W), Administration (R/W).',
            ),
            'docs/hcp-secrets.md': (
                'Permissions: Repository — Administration (read/write), Actions (read), Contents (read), Metadata (read), Pull requests (read/write).',
                'Organization — Members (read/write), Administration (read/write).',
            ),
        }
        for relative_path, permissions in expected.items():
            with self.subTest(path=relative_path):
                text = re.sub(r'\s+', ' ', (REFERENCES / relative_path).read_text(encoding='utf-8'))
                for permission in permissions:
                    self.assertIn(permission, text)
                self.assertIn('environments and deployment branch policies', text)
                self.assertIn('team membership', text)

    def test_both_github_app_steps_list_the_required_permissions(self) -> None:
        manifest = (REFERENCES / 'steps.yaml').read_text(encoding='utf-8')
        expected = {
            'gh-app': (
                'Permissions: Repo Administration(RW), Actions(R), Contents(R), Metadata(R), Pull requests(RW);',
                'Org Members(RW), Administration(RW).',
            ),
        }
        for step_id, permissions in expected.items():
            with self.subTest(step=step_id):
                step = re.sub(r'\s+', ' ', manifest.split(f'  - id: {step_id}\n', 1)[1].split('  - id: ', 1)[0])
                for permission in permissions:
                    self.assertIn(permission, step)
                self.assertIn('deployment branch policies', step)
                self.assertIn('team membership', step)

    def test_actions_apps_separate_read_and_write_permissions(self) -> None:
        plan_manifest = json.loads((REFERENCES / 'templates/apps/terraform-plan.json').read_text())
        apply_manifest = json.loads((REFERENCES / 'templates/apps/terraform-apply.json').read_text())
        self.assertTrue(all(permission == 'read' for permission in plan_manifest['default_permissions'].values()))
        for permission_name in ('administration', 'members', 'organization_administration'):
            self.assertEqual(apply_manifest['default_permissions'][permission_name], 'write')
        self.assertFalse(plan_manifest['hook_attributes']['active'])
        self.assertNotEqual(plan_manifest['name'], apply_manifest['name'])

    @unittest.skipUnless(os.name == 'posix', 'manifest checks use POSIX shell')
    def test_existing_secret_names_need_a_current_distinct_app_review(self) -> None:
        manifest = (REFERENCES / 'steps.yaml').read_text()
        app_step = manifest.split('  - id: gh-app-gha\n')[1].split('  - id: ')[0]
        app_check = textwrap.dedent(app_step.split('    check: |\n')[1].split('    produces:')[0])
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            (checkout / '.infra-copilot').mkdir()
            (checkout / '.infra-copilot/config.md').write_text('github_apps: {}\n')
            subprocess.run(['git', 'init', '-q'], cwd=checkout, check=True)
            subprocess.run(['git', 'add', '.infra-copilot'], cwd=checkout, check=True)
            subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                            'commit', '-qm', 'public review fixture'], cwd=checkout, check=True)
            binary_directory = checkout / 'bin'
            binary_directory.mkdir()
            secret_metadata = [{'name': name, 'updatedAt': '2025-01-01T00:00:00Z'}
                               for name in ('GH_APP_ID', 'GH_APP_INSTALLATION_ID', 'GH_APP_PEM')]
            gh_command = binary_directory / 'gh'
            gh_command.write_text("#!/bin/sh\nprintf '%s\\n' '" + json.dumps(secret_metadata) + "'\n")
            gh_command.chmod(0o755)
            environment = {**os.environ, 'PATH': f'{binary_directory}{os.pathsep}{os.environ["PATH"]}',
                           'REPO': 'acme/infra', 'GH_PLAN_APP_ID': '123', 'GH_APPLY_APP_ID': '456',
                           'GH_APPS_REVIEWED_AT': '2025-01-02T00:00:00Z'}
            reviewed = subprocess.run(['sh', '-c', app_check], cwd=checkout, env=environment,
                                      capture_output=True, text=True)
            self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
            for invalid_review in ({'GH_APPS_REVIEWED_AT': ''}, {'GH_APPLY_APP_ID': '123'},
                                   {'GH_APPS_REVIEWED_AT': '2024-12-31T00:00:00Z'}):
                rejected = subprocess.run(['sh', '-c', app_check], cwd=checkout,
                                          env={**environment, **invalid_review}, capture_output=True, text=True)
                self.assertEqual(rejected.returncode, 1, rejected.stderr)


if __name__ == '__main__':
    unittest.main()
