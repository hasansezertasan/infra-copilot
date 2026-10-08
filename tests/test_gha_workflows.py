"""Resume must reject legacy and partially upgraded workflow installations."""
from __future__ import annotations

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
        self.helper = self.root / '.github/scripts/terraform-destroy.cjs'
        self.helper.parent.mkdir()
        self.helper.write_text((REFERENCES / 'templates/terraform-destroy.cjs').read_text())
        self.commit()

    def git(self, *args: str) -> None:
        subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)

    def commit(self) -> None:
        self.git('add', '.github')
        self.git('commit', '--allow-empty', '-qm', 'test: record workflows')

    def check(self, *, references: bool = True) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, 'INFRA_COPILOT_REFERENCES': str(REFERENCES) if references else '',
               'ADDITIONAL_PROVIDER_SECRETS': '[{"name":"aws","credential_secrets":[{"name":"READ_TOKEN","scope":"plan","required":true},{"name":"WRITE_TOKEN","scope":"apply","required":true}]}]'}
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
            original.replace('run: terraform apply -lock=true', 'run: terraform apply -lock=false', 1),
            original.replace('run: terraform plan -lock=true -refresh=true', 'run: terraform plan -lock=true -refresh=false', 1),
            original.replace('secrets.GH_APP_PEM', 'secrets.GH_APP_READ_PEM'),
            original.replace('    environment: production\n', ''),
            original.replace('    environment: production', '    environment: staging'),
            original.replace('    environment: production', '    environment: production\n    environment: staging'),
            original.replace('      - name: Terraform Apply', '      - name: Terraform Apply\n        env:\n          TF_CLI_ARGS_apply: -lock=false', 1),
            original.replace('    runs-on:', '    env:\n      TF_CLI_ARGS_apply: -refresh=false\n    runs-on:', 1),
            original.replace('env:\n', 'env:\n  TF_CLI_ARGS: -refresh=false\n', 1),
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
            original.replace("              - '.github/scripts/terraform-destroy.cjs'\n", '', 1),
            original.replace("              - '.github/workflows/terraform-*.yml'\n", '', 1),
        ):
            with self.subTest(broken=broken):
                self.plan.write_text(broken)
                self.commit()
                self.assertEqual(self.check().returncode, 1)

    def test_writable_or_refreshing_github_plans_are_rejected(self) -> None:
        original = self.plan.read_text()
        for broken in (
            original.replace('-lock=false ', '', 1),
            original.replace('-refresh=false ', ''),
            original.replace('secrets.CLOUDFLARE_API_TOKEN_READ', 'secrets.CLOUDFLARE_API_TOKEN'),
            original.replace('secrets.GH_APP_READ_PEM', 'secrets.GH_APP_PEM'),
            original.replace('secrets.CLOUDFLARE_API_TOKEN_READ', 'secrets["CLOUDFLARE_API_TOKEN"]'),
            original.replace('secrets.GH_APP_READ_PEM', "secrets['GH_APP_PEM']"),
            original.replace('secrets.CLOUDFLARE_API_TOKEN_READ',
                             'toJSON(secrets) || secrets.CLOUDFLARE_API_TOKEN_READ'),
            original.replace('  plan-cloudflare:\n', '  plan-cloudflare:\n    environment: production\n'),
            original.replace('  plan-cloudflare:\n', '  plan-cloudflare:\n    "environment": production\n'),
            original.replace('  plan-cloudflare:\n', "  plan-cloudflare:\n    'environment': production\n"),
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

    def test_missing_dirty_and_outdated_helpers_cannot_skip_setup(self) -> None:
        original = self.helper.read_text()
        self.helper.unlink()
        self.commit()
        self.assertEqual(self.check().returncode, 1)
        self.helper.write_text(original)
        self.commit()
        self.helper.write_text(original + '// dirty\n')
        self.assertEqual(self.check().returncode, 1)
        self.commit()
        self.assertEqual(self.check().returncode, 1)

    def test_saved_plan_and_destructive_guard_cannot_be_bypassed(self) -> None:
        original = self.apply.read_text()
        start = original.index('      - name: Refuse destructive apply without opt-in')
        end = original.index("      - name: Refuse to apply a commit that is not main's tip", start)
        destroy = original[start:end]
        for broken in (
            original.replace(destroy, '', 1),
            original.replace(destroy, '', 1) + destroy,
            original.replace('await enforce(', '// await enforce(', 1),
            original.replace('      - name: Refuse destructive apply without opt-in',
                             '      - name: Refuse destructive apply without opt-in\n        continue-on-error: true', 1),
            original.replace('terraform apply -lock=true -no-color tfplan', 'terraform apply -auto-approve', 1),
            original.replace('terraform plan -lock=true -refresh=true -no-color -out=tfplan', 'terraform plan -no-color', 1),
            original.replace('run: terraform apply -lock=true -no-color tfplan',
                             'run: terraform apply -lock=true -no-color tfplan\n          && terraform apply -destroy -auto-approve', 1),
            original.replace('run: terraform plan -lock=true -refresh=true -no-color -out=tfplan',
                             'run: terraform plan -lock=true -refresh=true -no-color -out=tfplan\n          && terraform apply -auto-approve', 1),
            original.replace('      pull-requests: read', '      pull-requests: none', 1),
            original.replace('      - name: Terraform Apply',
                             '      - name: Replan\n        run: terraform plan -out=tfplan\n\n      - name: Terraform Apply', 1),
            original.replace("      - name: Refuse to apply a commit that is not main's tip",
                             "      - run: terraform plan -out=tfplan\n\n      - name: Refuse to apply a commit that is not main's tip", 1),
        ):
            with self.subTest(broken=broken):
                self.assertNotEqual(broken, original)
                self.apply.write_text(broken)
                self.commit()
                self.assertEqual(self.check().returncode, 1)

    def test_commented_or_misplaced_plan_inspection_is_rejected(self) -> None:
        original = self.plan.read_text()
        command = 'terraform show -json tfplan | node "$GITHUB_WORKSPACE/.github/scripts/terraform-destroy.cjs" > destroys.json'
        for broken in (
            original.replace(command, '# ' + command, 1),
            original.replace('            ' + command, '            true\n      # ' + command, 1),
            original.replace('        id: plan', '        id: other', 1),
            original.replace('        if: steps.plan.outputs.exitcode',
                             "        if: github.event_name == 'pull_request' && steps.plan.outputs.exitcode", 1),
        ):
            with self.subTest(broken=broken):
                self.plan.write_text(broken)
                self.commit()
                self.assertEqual(self.check().returncode, 1)

    def test_summary_must_precede_reporting_and_status_must_propagate_failure(self) -> None:
        original = self.plan.read_text()
        start = original.index('      - name: Summarize Destructive Changes')
        end = original.index('      - name: Post Plan to PR', start)
        inventory = original[start:end]
        reordered = original.replace(inventory, '', 1).replace(
            '      - name: Check Plan Status', inventory + '      - name: Check Plan Status', 1)
        for broken in (reordered,
                       original.replace("        if: steps.plan.outputs.exitcode != '0'", '        if: false', 1)):
            with self.subTest(broken=broken):
                self.plan.write_text(broken)
                self.commit()
                self.assertEqual(self.check().returncode, 1)

    def new_provider_check(self, provider: str = 'aws') -> subprocess.CompletedProcess[str]:
        manifest = (REFERENCES / 'steps.yaml').read_text()
        body = manifest.split('  - id: new-provider-workflow-gha\n', 1)[1].split('\n  - id:', 1)[0]
        match = re.search(r'^    check: \|\n((?:      .*\n|\n)+)', body, re.M)
        script = textwrap.dedent(match.group(1))
        return subprocess.run(['sh', '-c', script], cwd=self.root,
                               env={**os.environ, 'INFRA_COPILOT_REFERENCES': str(REFERENCES),
                                    'NEW_PROVIDER': provider,
                                    'NEW_PROVIDER_SECRETS': '[{"name":"READ_TOKEN","scope":"plan","required":true},{"name":"WRITE_TOKEN","scope":"apply","required":true}]'}, capture_output=True, text=True)

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
            credential_name = 'READ_TOKEN' if target == self.plan else 'WRITE_TOKEN'
            first = first.replace('CLOUDFLARE_API_TOKEN_READ', credential_name).replace('CLOUDFLARE_API_TOKEN', credential_name)
            target.write_text(text + f'\n  {prefix}-aws:' + first.replace('cloudflare', 'aws'))
        # Job output is mandatory for dispatch as well as PR filtering.
        self.plan.write_text(self.plan.read_text().replace('    outputs:\n',
            "    outputs:\n      aws: ${{ github.event_name == 'workflow_dispatch' && 'true' || steps.filter.outputs.aws }}\n", 1))
        self.plan.write_text(self.plan.read_text().replace('          filters: |\n',
            "          filters: |\n            aws:\n"
            "              - 'terraform/aws/**'\n"
            "              - '.github/workflows/terraform-*.yml'\n"
            "              - '.github/scripts/terraform-destroy.cjs'\n", 1))
        self.commit()
        self.assertEqual(self.new_provider_check().returncode, 0)
        # Inventory placement alone cannot catch apply incorrectly using a read secret.
        apply_original = self.apply.read_text()
        self.apply.write_text(apply_original.replace('secrets.WRITE_TOKEN', 'secrets.READ_TOKEN'))
        self.commit()
        self.assertEqual(self.new_provider_check().returncode, 1)
        self.apply.write_text(apply_original.replace('${{ secrets.WRITE_TOKEN }}', "''"))
        self.commit()
        self.assertEqual(self.new_provider_check().returncode, 1)
        self.apply.write_text(apply_original)
        self.commit()
        self.assertEqual(self.check().returncode, 0)
        plan_original = self.plan.read_text()
        for broken in (plan_original.replace('secrets.READ_TOKEN', 'secrets.WRITE_TOKEN'),
                       plan_original.replace('secrets.READ_TOKEN', 'secrets.UNDECLARED_TOKEN'),
                       plan_original.replace('${{ secrets.READ_TOKEN }}', "''")):
            self.plan.write_text(broken)
            self.commit()
            self.assertEqual(self.new_provider_check().returncode, 1)
        self.plan.write_text(plan_original)
        self.commit()
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
