"""Run the production apply-gate check against a routed `gh api` stub."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.ai-rulez/skills/infra-copilot/references/checks/gha-apply-gate.sh'

# Routes `gh api <path> [-q filter]` to env-provided JSON; FAIL_<KEY>=1 forces an error.
STUB = r'''#!/bin/sh
case "$2" in
  */deployment-branch-policies) key=POLICIES ;;
  */environments/production) key=ENV ;;
  orgs/*) key=ORG ;;
  repos/*) key=REPO_BODY ;;
  *) exit 1 ;;
esac
eval "fail=\${FAIL_$key:-0}; body=\${$key:-}"
if [ "$fail" != 0 ]; then
  if [ "$fail" = 404 ]; then
    printf 'gh: Not Found (HTTP 404)\n' >&2
  else
    printf 'gh: network error (HTTP 500)\n' >&2
  fi
  exit 1
fi
if [ "${3:-}" = -q ]; then printf '%s\n' "$body" | jq -r "$4"; else printf '%s\n' "$body"; fi
'''

REVIEWERS = [{'type': 'required_reviewers', 'reviewers': [{'id': 1}]}]
MAIN_ONLY = {'protected_branches': False, 'custom_branch_policies': True}


def env_body(rules: list, policy: dict | None = MAIN_ONLY) -> str:
    return json.dumps({'protection_rules': rules, 'deployment_branch_policy': policy})


@unittest.skipUnless(os.name == 'posix', 'shell check requires POSIX')
class ApplyGateTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'gh').write_text(STUB)
        (bin_dir / 'gh').chmod(0o755)
        self.env = {
            **os.environ,
            'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
            'REPO': 'acme/infra',
            'ENV': env_body([]),
            'POLICIES': json.dumps({'branch_policies': [{'name': 'main', 'type': 'branch'}]}),
            'REPO_BODY': json.dumps({'visibility': 'private'}),
            'ORG': json.dumps({'plan': {'name': 'team'}}),
        }

    def decide(self, row: str) -> None:
        (self.root / '.infra-copilot').mkdir(exist_ok=True)
        (self.root / '.infra-copilot/decisions.md').write_text(
            '| Decision | Choice | Status | Rationale |\n|---|---|---|---|\n' + row + '\n')

    def check(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(['sh', str(SCRIPT)], cwd=self.root, env=self.env,
                              capture_output=True, text=True)

    def test_reviewers_with_main_only_policy_pass(self) -> None:
        self.env['ENV'] = env_body(REVIEWERS)
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_production_environment_fails(self) -> None:
        self.env['FAIL_ENV'] = '404'
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn('does not exist', result.stderr)

    def test_reviewers_without_branch_policy_fail(self) -> None:
        for policy in [None, {'protected_branches': True, 'custom_branch_policies': False}]:
            with self.subTest(policy=policy):
                self.env['ENV'] = env_body(REVIEWERS, policy)
                self.assertEqual(self.check().returncode, 1)

    def test_policy_must_be_exactly_main(self) -> None:
        self.env['ENV'] = env_body(REVIEWERS)
        for policies in [[], [{'name': 'main'}, {'name': 'dev'}], [{'name': '*'}],
                         [{'name': 'main', 'type': 'tag'}]]:
            with self.subTest(policies=policies):
                self.env['POLICIES'] = json.dumps({'branch_policies': policies})
                self.assertEqual(self.check().returncode, 1)

    def test_empty_reviewer_list_is_not_reviewers(self) -> None:
        self.env['ENV'] = env_body([{'type': 'required_reviewers', 'reviewers': []}])
        self.env['REPO_BODY'] = json.dumps({'visibility': 'public'})
        self.assertEqual(self.check().returncode, 1)

    def test_private_team_repo_needs_a_recorded_gate(self) -> None:
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn('Apply gate', result.stderr)

    def test_private_team_repo_with_locked_gate_passes(self) -> None:
        for choice in ['merge-approval', '`dispatch`']:
            with self.subTest(choice=choice):
                self.decide(f'| Apply gate | {choice} | locked | Team plan has no reviewers |')
                result = self.check()
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_proposed_or_unknown_gate_does_not_count(self) -> None:
        for row in ['| Apply gate | merge-approval | proposed | x |', '| Apply gate | none | locked | x |']:
            with self.subTest(row=row):
                self.decide(row)
                self.assertEqual(self.check().returncode, 1)

    def test_user_owned_private_repo_can_use_a_gate(self) -> None:
        self.env['FAIL_ORG'] = '404'
        self.decide('| Apply gate | dispatch | locked | x |')
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_org_plan_read_failure_is_unknown(self) -> None:
        self.env['FAIL_ORG'] = '1'
        self.decide('| Apply gate | dispatch | locked | x |')
        result = self.check()
        self.assertEqual(result.returncode, 2)
        self.assertIn('organization plan could not be read', result.stderr)

    def test_gate_cannot_replace_available_reviewers(self) -> None:
        self.decide('| Apply gate | merge-approval | locked | x |')
        for repo, org in [({'visibility': 'public'}, {'plan': {'name': 'team'}}),
                          ({'visibility': 'private'}, {'plan': {'name': 'enterprise'}}),
                          ({'visibility': 'private'}, {'plan': {'name': 'Enterprise'}})]:
            with self.subTest(repo=repo, org=org):
                self.env['REPO_BODY'], self.env['ORG'] = json.dumps(repo), json.dumps(org)
                self.assertEqual(self.check().returncode, 1)

    def test_unreadable_api_is_unknown(self) -> None:
        for key in ['FAIL_ENV', 'FAIL_POLICIES', 'FAIL_REPO_BODY']:
            with self.subTest(key=key):
                env = dict(self.env)
                self.env[key] = '1'
                self.assertEqual(self.check().returncode, 2)
                self.env = env


if __name__ == '__main__':
    unittest.main()
