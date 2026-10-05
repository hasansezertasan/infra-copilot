"""Run the new-leaf safety gate against committed workflows and an API stub."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.ai-rulez/skills/infra-copilot/references/checks/gha-provider-safety.sh'


@unittest.skipUnless(os.name == 'posix', 'shell check requires POSIX')
class ProviderSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.com')
        self.workflows = self.root / '.github/workflows'
        self.workflows.mkdir(parents=True)
        self.plan = self.workflows / 'terraform-plan.yml'
        self.apply = self.workflows / 'terraform-apply.yml'
        self.plan.write_text("""on:
  pull_request:
  workflow_dispatch:
jobs:
  plan-aws:
    if: needs.changes.outputs.aws == 'true' && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)
    runs-on: ubuntu-latest
    steps: []
""")
        self.apply.write_text("""on:
  push:
    branches: [main]
jobs:
  apply-aws:
    environment: production
    steps: []
""")
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        stub = self.bin / 'gh'
        stub.write_text('#!/bin/sh\n[ "${API_FAIL:-0}" = 0 ] || exit 1\nprintf "%s\\n" "$API_BODY"\n')
        stub.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
                    'NEW_PROVIDER': 'aws', 'REPO': 'owner/repo',
                    'API_BODY': json.dumps({'protection_rules': [{'type': 'required_reviewers', 'reviewers': [{'id': 1}]}]})}
        self.commit()

    def git(self, *args: str) -> None:
        subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)

    def commit(self) -> None:
        self.git('add', '.github')
        self.git('commit', '-qm', 'test: record workflows')

    def check(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(['sh', str(SCRIPT)], cwd=self.root, env=self.env, capture_output=True, text=True)

    def test_supported_guard_and_reviewers_pass(self) -> None:
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unprotected_new_job_cannot_borrow_another_jobs_guard(self) -> None:
        original = self.plan.read_text()
        other = original.replace('plan-aws:', 'plan-other:')
        self.plan.write_text(other + '  plan-aws:\n    steps: []\n')
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_or_can_never_bypass_the_guard(self) -> None:
        self.plan.write_text(self.plan.read_text().replace(" == 'true' &&", " == 'true' ||"))
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_bracket_output_supports_hyphenated_provider_names(self) -> None:
        self.env['NEW_PROVIDER'] = 'aws-prod'
        self.plan.write_text(self.plan.read_text().replace('plan-aws:', 'plan-aws-prod:').replace('outputs.aws', "outputs['aws-prod']"))
        self.apply.write_text(self.apply.read_text().replace('apply-aws:', 'apply-aws-prod:'))
        self.commit()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_duplicate_environment_cannot_override_protection(self) -> None:
        self.apply.write_text(self.apply.read_text().replace('    steps: []', '    environment: unprotected\n    steps: []'))
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_dirty_workflow_is_not_evidence(self) -> None:
        self.plan.write_text(self.plan.read_text() + '# not committed\n')
        self.assertEqual(self.check().returncode, 1)

    def test_target_event_is_rejected(self) -> None:
        self.plan.write_text(self.plan.read_text().replace('pull_request:', 'pull_request_target:'))
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_apply_requires_protected_environment(self) -> None:
        self.apply.write_text(self.apply.read_text().replace('environment: production', 'environment: unprotected'))
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_reviewers_must_be_required(self) -> None:
        self.env['API_BODY'] = '{"protection_rules": []}'
        self.assertEqual(self.check().returncode, 1)

    def test_unreadable_api_is_unknown(self) -> None:
        self.env['API_FAIL'] = '1'
        self.assertEqual(self.check().returncode, 2)

    def test_malformed_api_is_unknown(self) -> None:
        self.env['API_BODY'] = 'not json'
        self.assertEqual(self.check().returncode, 2)


if __name__ == '__main__':
    unittest.main()
