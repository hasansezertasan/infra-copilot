"""Resume must reject legacy and partially upgraded workflow installations."""
from __future__ import annotations

import json
import os
import re
import textwrap
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / '.ai-rulez/skills/infra-copilot/references'
SCRIPT = REFERENCES / 'checks/gha-workflows.sh'


@unittest.skipUnless(os.name == 'posix', 'workflow check requires POSIX shell')
class WorkflowSetupTests(unittest.TestCase):
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
        self.plan.write_text((REFERENCES / 'templates/terraform-plan.yml').read_text())
        self.apply.write_text((REFERENCES / 'templates/terraform-apply.yml').read_text())
        self.commit()

    def git(self, *args: str) -> None:
        subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)

    def commit(self) -> None:
        self.git('add', '.github')
        self.git('commit', '--allow-empty', '-qm', 'test: record workflows')

    def check(self, *, references: bool = True) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, 'INFRA_COPILOT_REFERENCES': str(REFERENCES) if references else '',
               'BACKEND': 'object-storage', 'ADDITIONAL_PROVIDER_NAMES': '[]'}
        return subprocess.run(['sh', str(SCRIPT)], cwd=self.root, env=env,
                              capture_output=True, text=True)

    def test_shipped_workflows_pass(self) -> None:
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_workflows_do_not_skip_setup(self) -> None:
        self.plan.write_text(self.plan.read_text().replace('  workflow_dispatch:\n', '')
                             .replace("        if: github.event_name == 'pull_request'\n", '')
                             .replace("github.event_name == 'workflow_dispatch' && 'true' || ", ''))
        old_apply = self.apply.read_text().replace('  workflow_dispatch:\n', '')
        old_apply = old_apply.replace('    branches: [main]', '    branches: [main]\n    paths:\n      - terraform/**')
        old_apply = old_apply.replace('terraform-apply-${{ github.ref }}', 'terraform-apply')
        for leaf in ('cloudflare', 'github'):
            old_apply = old_apply.replace(f'  apply-{leaf}:\n',
                f"  apply-{leaf}:\n    needs: changes\n    if: needs.changes.outputs.{leaf} == 'true'\n")
        self.apply.write_text(old_apply)
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_partial_apply_upgrades_are_rejected(self) -> None:
        original = self.apply.read_text()
        guard_start = original.index("      - name: Refuse to apply a commit that is not main's tip")
        guard_end = original.index('      - name: Terraform Apply', guard_start)
        guard = original[guard_start:guard_end]
        for broken in (
            original.replace('  workflow_dispatch:\n', ''),
            original.replace('    branches: [main]', '    branches: [main]\n    paths:\n      - terraform/**'),
            original.replace('    branches: [main]', '    branches: [main]\n    paths-ignore:\n      - docs/**'),
            original.replace('terraform-apply-${{ github.ref }}', 'terraform-apply'),
            original.replace('cancel-in-progress: false', 'cancel-in-progress: true'),
            original.replace('    branches: [main]\n', '').replace('  workflow_dispatch:', '  workflow_dispatch:\n    branches: [main]'),
            original + '\n  apply-cloudflare:\n    steps: []\n',
            original.replace('  apply-cloudflare:', '  other:'),
            original.replace('  apply-github:', '    if: false\n\n  apply-github:'),
            original.replace('  apply-github:', '    needs: skipped-job\n\n  apply-github:'),
            original.replace('    runs-on:', "    if: needs.changes.outputs.cloudflare == 'true'\n    runs-on:", 1),
            original.replace('    runs-on:', '    needs: changes\n    runs-on:', 1),
            original.replace(guard, '', 1),
            original.replace('            exit 1', '            exit 0'),
            original.replace('          if [ "$GITHUB_REF" != "refs/heads/main" ] ||', '          if'),
            original.replace(guard, '', 1) + guard,
            original.replace('      - name: Terraform Apply', '      - name: Terraform Apply\n        if: false', 1),
            original.replace('      - name: Terraform Apply', '      - name: Terraform Apply\n        continue-on-error: true', 1),
        ):
            with self.subTest(broken=broken):
                self.apply.write_text(broken)
                self.commit()
                self.assertEqual(self.check().returncode, 1)

    def test_partial_dispatch_plans_are_rejected(self) -> None:
        original = self.plan.read_text()
        for broken in (
            original.replace('  workflow_dispatch:\n', ''),
            original.replace('  changes:\n', "  changes:\n    if: github.event_name == 'pull_request'\n"),
            original.replace('  plan-cloudflare:', "    if: github.event_name == 'pull_request'\n\n  plan-cloudflare:"),
            original.replace('  plan-cloudflare:', '    needs: skipped-job\n\n  plan-cloudflare:'),
            original.replace('    needs: changes', '    needs: [changes, skipped-job]', 1),
            original.replace('    needs: changes\n', '', 1),
            original.replace("        if: github.event_name == 'pull_request'\n", ''),
            original.replace("github.event_name == 'workflow_dispatch' && 'true' || ", ''),
            original.replace("    if: needs.changes.outputs.cloudflare == 'true'", '    if: false && needs.changes.outputs.cloudflare'),
            original.replace('      cloudflare:', '      cloudflare: false\n      cloudflare:', 1),
        ):
            with self.subTest(broken=broken):
                self.plan.write_text(broken)
                self.commit()
                self.assertEqual(self.check().returncode, 1)

    def test_dispatch_gate_requires_a_locked_decision_and_no_auto_apply(self) -> None:
        original = self.apply.read_text()
        dispatch_only = original.replace('  push:\n    branches: [main]\n', '')
        decisions = self.root / '.infra-copilot/decisions.md'
        decisions.parent.mkdir()
        for choice, status, expected in (('dispatch', 'locked', 0),
                                          ('dispatch', 'open', 1),
                                          ('merge-approval', 'locked', 1)):
            with self.subTest(choice=choice, status=status):
                decisions.write_text(f'| Apply gate | {choice} | {status} |\n')
                self.git('add', '.infra-copilot')
                self.apply.write_text(dispatch_only)
                self.commit()
                self.assertEqual(self.check().returncode, expected)
        decisions.write_text('| Apply gate | dispatch | locked |\n')
        self.git('add', '.infra-copilot')
        self.apply.write_text(original)
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_dirty_workflows_are_not_evidence(self) -> None:
        self.apply.write_text(self.apply.read_text() + '# uncommitted\n')
        self.assertEqual(self.check().returncode, 1)

    def test_missing_references_are_unknown(self) -> None:
        self.assertEqual(self.check(references=False).returncode, 2)

    def new_provider_check(self, provider: str = 'aws') -> subprocess.CompletedProcess[str]:
        manifest = (REFERENCES / 'steps.yaml').read_text()
        body = manifest.split('  - id: new-provider-workflow-gha\n', 1)[1].split('\n  - id:', 1)[0]
        match = re.search(r'^    check: \|\n((?:      .*\n|\n)+)', body, re.M)
        script = textwrap.dedent(match.group(1))
        return subprocess.run(['sh', '-c', script], cwd=self.root,
                               env={**os.environ, 'INFRA_COPILOT_REFERENCES': str(REFERENCES),
                                    'NEW_PROVIDER': provider, 'BACKEND': 'object-storage',
                                    'ADDITIONAL_PROVIDER_NAMES': json.dumps([provider])}, capture_output=True, text=True)

    def test_requested_provider_must_exist_as_actual_jobs(self) -> None:
        # Comments can satisfy the old name/path grep, but are not provider jobs.
        self.plan.write_text(self.plan.read_text() + '# plan-aws: terraform/aws\n')
        self.apply.write_text(self.apply.read_text() + '# apply-aws: terraform/aws\n')
        self.commit()
        self.assertEqual(self.new_provider_check().returncode, 1)
        for provider in ('', '../aws'):
            self.assertEqual(self.new_provider_check(provider).returncode, 2)

    def test_every_added_leaf_requires_a_guard_and_dispatch_plan(self) -> None:
        for target in (self.plan, self.apply):
            text = target.read_text()
            # Append a copy of the first provider job, with provider names changed.
            prefix = 'plan' if target == self.plan else 'apply'
            first = text.split(f'  {prefix}-cloudflare:', 1)[1].split(f'\n  {prefix}-github:', 1)[0]
            target.write_text(text + f'\n  {prefix}-aws:' + first.replace('cloudflare', 'aws'))
        # Job output is mandatory for dispatch as well as PR filtering.
        self.plan.write_text(self.plan.read_text().replace('    outputs:\n',
            "    outputs:\n      aws: ${{ github.event_name == 'workflow_dispatch' && 'true' || steps.filter.outputs.aws }}\n", 1))
        self.commit()
        # The legacy unfiltered output is insufficient: a new provider must also
        # declare its backend route and participate in the required aggregate.
        self.assertEqual(self.new_provider_check().returncode, 1)
        plan_original = self.plan.read_text()
        self.plan.write_text(plan_original.replace("      aws: ${{ github.event_name == 'workflow_dispatch' && 'true' || steps.filter.outputs.aws }}",
                                                   "      aws: ${{ steps.filter.outputs.aws }}"))
        self.commit()
        self.assertEqual(self.new_provider_check().returncode, 1)
        self.plan.write_text(plan_original)
        self.apply.write_text(self.apply.read_text().replace('  apply-aws:\n', '  apply-aws:\n    if: false\n'))
        self.commit()
        self.assertEqual(self.new_provider_check().returncode, 1)


if __name__ == '__main__':
    unittest.main()
