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
        stub.write_text('#!/bin/sh\n[ "${API_FAIL:-0}" = 0 ] || exit 1\n'
                        'case "$2" in */deployment-branch-policies) printf "%s\\n" "$POLICIES_BODY" ;;\n'
                        '*) printf "%s\\n" "$API_BODY" ;; esac\n')
        stub.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
                    'NEW_PROVIDER': 'aws', 'REPO': 'owner/repo',
                    'INFRA_COPILOT_REFERENCES': str(SCRIPT.parent.parent),
                    'POLICIES_BODY': json.dumps({'branch_policies': [{'name': 'main', 'type': 'branch'}]}),
                    'API_BODY': json.dumps({'protection_rules': [{'type': 'required_reviewers', 'reviewers': [{'id': 1}]}],
                                            'deployment_branch_policy': {'protected_branches': False,
                                                                         'custom_branch_policies': True}})}
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

    def test_workflow_oidc_permission_is_rejected(self) -> None:
        self.plan.write_text('permissions:\n  id-token: write\n' + self.plan.read_text())
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_unguarded_job_oidc_permission_is_rejected(self) -> None:
        self.plan.write_text(self.plan.read_text() +
                             '  validate:\n    permissions:\n      id-token: write\n    steps: []\n')
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_unguarded_job_secret_access_is_rejected(self) -> None:
        self.plan.write_text(self.plan.read_text() +
                             '  validate:\n    env:\n      TOKEN: ${{ secrets.TOKEN }}\n    steps: []\n')
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_unguarded_inherited_and_whole_context_secrets_are_rejected(self) -> None:
        original = self.plan.read_text()
        for credentials in ['    secrets: inherit\n', '    env: {TOKEN: "${{ toJSON(secrets) }}"}\n']:
            with self.subTest(credentials=credentials):
                self.plan.write_text(original + '  validate:\n' + credentials + '    steps: []\n')
                self.commit()
                self.assertEqual(self.check().returncode, 1)

    def test_shipped_templates_keep_oidc_in_guarded_jobs(self) -> None:
        templates = SCRIPT.parent.parent / 'templates'
        for target, filename in [(self.plan, 'terraform-plan.yml'), (self.apply, 'terraform-apply.yml')]:
            target.write_text((templates / filename).read_text().replace('cloudflare', 'aws'))
        self.commit()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_credential_alias_cannot_bypass_job_guard(self) -> None:
        original = self.plan.read_text()
        for name in ['provider_credentials', '1']:
            with self.subTest(name=name):
                self.plan.write_text(original.replace(
                    '    steps: []', f'    env: &{name}\n      TOKEN: ${{{{ secrets.TOKEN }}}}\n    steps: []') +
                    f'  validate:\n    env: *{name}\n    steps: []\n')
                self.commit()
                self.assertEqual(self.check().returncode, 1)

    def test_escaped_permission_key_is_rejected(self) -> None:
        self.plan.write_text(self.plan.read_text() +
                             '  validate:\n    permissions:\n      "id-\\u0074oken": write\n    steps: []\n')
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_workflow_oidc_after_jobs_is_rejected(self) -> None:
        self.plan.write_text(self.plan.read_text() + 'permissions:\n    id-token: write\n')
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_workflow_credentials_after_jobs_are_rejected(self) -> None:
        self.plan.write_text(self.plan.read_text() + 'env: {TOKEN: "${{ secrets.TOKEN }}"}\n')
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_flow_permissions_cannot_hide_workflow_oidc(self) -> None:
        self.plan.write_text("permissions: {'id-token': write}\n" + self.plan.read_text())
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_guarded_job_oidc_permission_passes(self) -> None:
        self.plan.write_text(self.plan.read_text().replace(
            '    runs-on:', '    permissions:\n      id-token: write\n    runs-on:'))
        self.commit()
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

    def test_flow_target_event_is_rejected(self) -> None:
        self.plan.write_text(self.plan.read_text().replace('on:\n  pull_request:\n  workflow_dispatch:', 'on: [pull_request_target, workflow_dispatch]'))
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_scalar_target_event_is_rejected(self) -> None:
        self.plan.write_text(self.plan.read_text().replace('on:\n  pull_request:\n  workflow_dispatch:', 'on: pull_request_target'))
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_whitespace_inside_event_literal_cannot_change_the_guard(self) -> None:
        self.plan.write_text(self.plan.read_text().replace("!= 'pull_request'", "!= 'pull_ request'"))
        self.commit()
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
        self.env['API_BODY'] = json.dumps({'protection_rules': [], 'deployment_branch_policy': {
            'protected_branches': False, 'custom_branch_policies': True}})
        # The repo-visibility lookup returns this body too; without .visibility the gate
        # treats the repo as private, so a missing decision row is what fails it.
        self.assertEqual(self.check().returncode, 1)

    def test_apply_gate_is_required(self) -> None:
        self.env['POLICIES_BODY'] = json.dumps({'branch_policies': []})
        self.assertEqual(self.check().returncode, 1)

    def test_missing_references_is_unknown(self) -> None:
        del self.env['INFRA_COPILOT_REFERENCES']
        self.assertEqual(self.check().returncode, 2)

    def test_unreadable_api_is_unknown(self) -> None:
        self.env['API_FAIL'] = '1'
        self.assertEqual(self.check().returncode, 2)

    def test_malformed_api_is_unknown(self) -> None:
        self.env['API_BODY'] = 'not json'
        self.assertEqual(self.check().returncode, 2)


if __name__ == '__main__':
    unittest.main()
