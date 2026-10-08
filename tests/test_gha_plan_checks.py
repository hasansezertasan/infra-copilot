"""Unreadable Actions evidence is distinct from a known failed or missing plan."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REFERENCES = Path(__file__).resolve().parents[1] / '.ai-rulez/skills/infra-copilot/references'
MEMBERS = ('plan-cloudflare-gha', 'plan-github-gha', 'new-provider-plan-gha')


@unittest.skipUnless(os.name == 'posix' and shutil.which('jq'), 'POSIX shell and jq required')
class ActionsPlanEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.checkout = Path(temporary.name)
        for relative_path in ('terraform/cloudflare', 'terraform/github', 'terraform/gcp',
                              '.infra-copilot', '.github/workflows', 'references/checks', 'bin'):
            (self.checkout / relative_path).mkdir(parents=True)
        (self.checkout / '.infra-copilot/config.md').write_text('backend: object-storage\n')
        for provider_name in ('cloudflare', 'github', 'gcp'):
            (self.checkout / f'terraform/{provider_name}/versions.tf').write_text('terraform {}\n')
        subprocess.run(['git', 'init', '-q'], cwd=self.checkout, check=True)
        subprocess.run(['git', 'add', 'terraform', '.infra-copilot'], cwd=self.checkout, check=True)
        subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                        'commit', '-qm', 'public plan fixture'], cwd=self.checkout, check=True)
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.checkout, check=True,
                              capture_output=True, text=True).stdout.strip()
        # Execution routing has separate behavioral coverage. Isolate API failures here.
        (self.checkout / 'references/checks/workflow-routing.sh').write_text('#!/bin/sh\nexit 0\n')
        gh_command = self.checkout / 'bin/gh'
        gh_command.write_text('''#!/bin/sh
case "$1 $2" in
  'run list') [ "$TEST_LIST_EXIT" = 0 ] || exit "$TEST_LIST_EXIT"; printf '%s\\n' "$TEST_RUN_INFO" ;;
  'run view') [ "$TEST_VIEW_EXIT" = 0 ] || exit "$TEST_VIEW_EXIT"; printf '%s\\n' "$TEST_JOB_NAMES" ;;
  *) exit 99 ;;
esac
''')
        gh_command.chmod(0o755)
        self.environment = {**os.environ, 'PATH': f'{self.checkout / "bin"}{os.pathsep}{os.environ["PATH"]}',
                            'INFRA_COPILOT_REFERENCES': str(self.checkout / 'references'),
                            'REPO': 'acme/infra', 'NEW_PROVIDER': 'gcp',
                            'TEST_LIST_EXIT': '0', 'TEST_VIEW_EXIT': '0',
                            'TEST_RUN_INFO': json.dumps({'databaseId': 123, 'headSha': head,
                                                         'conclusion': 'success', 'event': 'workflow_dispatch'}),
                            'TEST_JOB_NAMES': 'plan-cloudflare\nplan-github\nplan-gcp'}

    def check_evidence(self, member_name: str, **overrides: str) -> subprocess.CompletedProcess[str]:
        manifest_text = (REFERENCES / 'steps.yaml').read_text()
        member_body = manifest_text.split(f'  - id: {member_name}\n')[1].split('  - id: ')[0]
        check_body = textwrap.dedent(member_body.split('    check: |\n')[1].split('    produces:')[0])
        return subprocess.run(['sh', '-c', check_body], cwd=self.checkout,
                              env={**self.environment, **overrides}, capture_output=True, text=True)

    def test_list_and_view_api_failures_are_unknown_for_every_plan_member(self) -> None:
        for member_name in MEMBERS:
            for failures in ({'TEST_LIST_EXIT': '4'}, {'TEST_LIST_EXIT': '1'}, {'TEST_VIEW_EXIT': '4'},
                             {'TEST_VIEW_EXIT': '1'}, {'TEST_RUN_INFO': '{broken json'}):
                with self.subTest(member=member_name, failures=failures):
                    self.assertEqual(self.check_evidence(member_name, **failures).returncode, 2)

    def test_successful_plans_pass_for_every_plan_member(self) -> None:
        for member_name in MEMBERS:
            with self.subTest(member=member_name):
                completed = self.check_evidence(member_name)
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_known_missing_or_failed_plans_are_red(self) -> None:
        failed_run = json.loads(self.environment['TEST_RUN_INFO'])
        failed_run['conclusion'] = 'failure'
        for member_name in MEMBERS:
            for evidence in ({'TEST_RUN_INFO': 'null'}, {'TEST_JOB_NAMES': ''},
                             {'TEST_RUN_INFO': json.dumps(failed_run)}):
                with self.subTest(member=member_name, evidence=evidence):
                    self.assertEqual(self.check_evidence(member_name, **evidence).returncode, 1)
