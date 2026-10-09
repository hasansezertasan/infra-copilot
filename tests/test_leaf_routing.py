"""Execute source checks and manifest selectors against mixed cutover inventories.

Sources are intentional: the coordinator generates once after shared-worktree edits.
No Terraform runner or cloud credentials are needed for these routing regressions.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / '.ai-rulez/skills/infra-copilot/references'


@unittest.skipUnless(os.name == 'posix' and shutil.which('jq'), 'POSIX shell and jq required')
class LeafRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.checkout = Path(temporary.name)
        self.environment = {
            **os.environ,
            'BACKEND': 'hcp',
            'LEAF_BACKENDS': '{"github":"object-storage"}',
            'ADDITIONAL_PROVIDER_NAMES': '[]',
            'INFRA_COPILOT_REFERENCES': str(REFERENCES),
        }

    def execute_check(self, script_name: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ['sh', str(REFERENCES / 'checks' / script_name)],
            cwd=self.checkout, env=self.environment, capture_output=True, text=True,
        )

    def resolve_routing(self) -> dict[str, object]:
        completed = self.execute_check('leaf-routing.sh')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def export_routing(self) -> dict[str, object]:
        inventory = self.resolve_routing()
        for field_name in ('hcp_leaves', 'object_storage_leaves', 'hcp_bootstrap_leaves',
                           'object_storage_bootstrap_leaves'):
            self.environment[field_name.upper()] = json.dumps(inventory[field_name])
        for field_name in ('has_hcp', 'has_object_storage', 'has_hcp_bootstrap', 'has_object_storage_bootstrap'):
            self.environment[field_name.upper()] = str(inventory[field_name]).lower()
        effective = inventory['effective']
        self.environment['CLOUDFLARE_BACKEND'] = effective['cloudflare']
        self.environment['GITHUB_BACKEND'] = effective['github']
        return inventory

    def test_default_hcp_github_cutover(self) -> None:
        inventory = self.resolve_routing()
        self.assertEqual(inventory['hcp_leaves'], ['cloudflare'])
        self.assertEqual(inventory['object_storage_leaves'], ['github'])
        self.assertTrue(inventory['has_hcp'])
        self.assertTrue(inventory['has_object_storage'])

    def test_absent_map_preserves_explicit_default(self) -> None:
        del self.environment['LEAF_BACKENDS']
        self.assertEqual(self.resolve_routing()['hcp_leaves'], ['cloudflare', 'github'])

    def test_invalid_maps_fail_before_checks(self) -> None:
        for overrides in ('null', '[]', '"hcp"', '', '{', '{"githb":"object-storage"}',
                          '{"github":null}', '{"github":""}', '{"github":"local"}',
                          '{"gcp":"hcp"}', '{"../github":"hcp"}'):
            with self.subTest(overrides=overrides):
                self.environment['LEAF_BACKENDS'] = overrides
                completed = self.execute_check('leaf-routing.sh')
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stdout, '')

    def test_invalid_default_cannot_be_hidden_by_complete_overrides(self) -> None:
        self.environment['LEAF_BACKENDS'] = '{"cloudflare":"hcp","github":"object-storage"}'
        for default_value in ('', 'local'):
            self.environment['BACKEND'] = default_value
            self.assertEqual(self.execute_check('leaf-routing.sh').returncode, 2)

    def test_invalid_adoption_names_fail_closed(self) -> None:
        for declaration in ('null', '{}', '["gcp","gcp"]', '["github"]', '["modules"]', '["../gcp"]'):
            self.environment['ADDITIONAL_PROVIDER_NAMES'] = declaration
            self.assertEqual(self.execute_check('leaf-routing.sh').returncode, 2)

    def test_undeclared_actual_leaf_blocks_preflight(self) -> None:
        (self.checkout / 'terraform/gcp').mkdir(parents=True)
        completed = self.execute_check('leaf-routing.sh')
        self.assertEqual(completed.returncode, 2)
        self.assertIn('undeclared Terraform leaf gcp', completed.stderr)
        self.environment['ADDITIONAL_PROVIDER_NAMES'] = '["gcp"]'
        self.assertEqual(self.execute_check('leaf-routing.sh').returncode, 0)

    def selected_members(self) -> set[str]:
        manifest_text = (REFERENCES / 'steps.yaml').read_text(encoding='utf-8')
        selected = set()
        for match in re.finditer(r'^  - id: ([^\n]+)\n(.*?)(?=^  - id: |\Z)', manifest_text, re.M | re.S):
            member_name, member_body = match.groups()
            if '    implementation:' not in member_body:
                continue
            condition = re.search(r"^    when: '([^\n]+)'$", member_body, re.M)
            if condition is None:
                continue
            result = subprocess.run(['sh', '-c', condition[1]], env=self.environment, capture_output=True)
            if result.returncode == 0:
                selected.add(member_name)
        return selected

    def test_mixed_bootstrap_selects_real_leaf_steps_and_both_protections(self) -> None:
        self.export_routing()
        selected = self.selected_members()
        self.assertTrue({'hcp-login', 'workspaces-create', 'state-bucket', 'backend-config',
                         'backend-identity', 'gha-workflows', 'cf-token', 'gh-app-gha',
                         'plan-cloudflare', 'plan-github-gha', 'hcp-apply-scope',
                         'status-check-context', 'status-check-gha'} <= selected)
        self.assertTrue({'gh-app', 'cf-token-gha', 'plan-github', 'plan-cloudflare-gha'}.isdisjoint(selected))

    def test_backend_configuration_check_filters_hcp_leaf(self) -> None:
        self.export_routing()
        self.environment.update(STATE_BACKEND='gcs', STATE_BUCKET='acme-state', STATE_PREFIX='terraform/state')
        hcp_directory = self.checkout / 'terraform/cloudflare'
        hcp_directory.mkdir(parents=True)
        (hcp_directory / 'versions.tf').write_text('terraform { cloud {} }\n', encoding='utf-8')
        runner_directory = self.checkout / 'terraform/github'
        runner_directory.mkdir(parents=True)
        runner_backend = runner_directory / 'backend.tf'
        runner_backend.write_text(
            'terraform { backend "gcs" { bucket = "acme-state"\n'
            'prefix = "terraform/state/github" } }\n', encoding='utf-8')
        subprocess.run(['git', 'init', '-q'], cwd=self.checkout, check=True)
        subprocess.run(['git', 'add', 'terraform'], cwd=self.checkout, check=True)
        subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                        'commit', '-qm', 'fresh backend fixture'], cwd=self.checkout, check=True)
        manifest_text = (REFERENCES / 'steps.yaml').read_text(encoding='utf-8')
        member_body = manifest_text.split('  - id: backend-config\n', 1)[1].split('  - id: ', 1)[0]
        check_body = member_body.split('    check: |\n', 1)[1].split('    produces:', 1)[0]
        check_body = '\n'.join(line.removeprefix('      ') for line in check_body.splitlines())
        completed = subprocess.run(['sh', '-c', check_body], cwd=self.checkout, env=self.environment,
                                   capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        runner_backend.write_text('terraform { cloud {} }\n', encoding='utf-8')
        completed = subprocess.run(['sh', '-c', check_body], cwd=self.checkout, env=self.environment,
                                   capture_output=True, text=True)
        self.assertEqual(completed.returncode, 1)

    def test_additional_provider_drives_service_presence_not_bootstrap(self) -> None:
        self.environment.update(BACKEND='object-storage', LEAF_BACKENDS='{"gcp":"hcp"}',
                                ADDITIONAL_PROVIDER_NAMES='["gcp","aws"]')
        inventory = self.export_routing()
        self.assertEqual(inventory['hcp_leaves'], ['gcp'])
        self.assertFalse(inventory['has_hcp_bootstrap'])
        self.environment['NEW_PROVIDER_BACKEND'] = 'hcp'
        selected = self.selected_members()
        self.assertIn('hcp-login', selected)
        self.assertNotIn('workspaces-create', selected)
        self.assertIn('new-provider-workspace', selected)
        self.assertNotIn('new-provider-workflow-gha', selected)
        self.environment['NEW_PROVIDER_BACKEND'] = 'object-storage'
        selected = self.selected_members()
        self.assertIn('new-provider-workflow-gha', selected)
        self.assertNotIn('new-provider-workspace', selected)

    def write_workflows(self, cloudflare_backend: str = 'hcp', github_backend: str = 'object-storage') -> None:
        workflow_directory = self.checkout / '.github/workflows'
        workflow_directory.mkdir(parents=True, exist_ok=True)
        for workflow_name in ('terraform-plan.yml', 'terraform-apply.yml'):
            (workflow_directory / workflow_name).write_text(
                (REFERENCES / 'templates' / workflow_name).read_text().replace(
                    'CLOUDFLARE_BACKEND: object-storage', f'CLOUDFLARE_BACKEND: {cloudflare_backend}'
                ).replace('GITHUB_BACKEND: object-storage', f'GITHUB_BACKEND: {github_backend}'),
                encoding='utf-8',
            )

    def test_static_workflows_must_agree_with_effective_not_default(self) -> None:
        self.write_workflows()
        completed = self.execute_check('workflow-routing.sh')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.write_workflows(cloudflare_backend='object-storage')
        completed = self.execute_check('workflow-routing.sh')
        self.assertEqual(completed.returncode, 1)
        self.assertIn('effective config requires hcp', completed.stderr)

    def test_apply_disagreement_and_local_overrides_cannot_pass(self) -> None:
        self.write_workflows()
        workflow_path = self.checkout / '.github/workflows/terraform-apply.yml'
        workflow_text = workflow_path.read_text(encoding='utf-8')
        workflow_path.write_text(workflow_text.replace('GITHUB_BACKEND: object-storage', 'GITHUB_BACKEND: hcp'))
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 1)
        workflow_path.write_text(workflow_text + '  apply:\n    env:\n      GITHUB_BACKEND: hcp\n')
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 2)

    def test_additional_provider_workflow_literal_matches_override(self) -> None:
        self.environment.update(ADDITIONAL_PROVIDER_NAMES='["gcp-prod"]',
                                LEAF_BACKENDS='{"github":"object-storage","gcp-prod":"object-storage"}',
                                ROUTING_PROVIDER='gcp-prod')
        self.write_workflows()
        for workflow_name in ('terraform-plan.yml', 'terraform-apply.yml'):
            workflow_path = self.checkout / '.github/workflows' / workflow_name
            prefix = 'plan' if workflow_name == 'terraform-plan.yml' else 'apply'
            changed_expression = "${{ github.event_name == 'workflow_dispatch' && 'true' || steps.filter.outputs.gcp-prod }}" if prefix == 'plan' else "'true'"
            github_expression = "${{ github.event_name == 'workflow_dispatch' && 'true' || steps.filter.outputs.github }}" if prefix == 'plan' else "'true'"
            workflow_text = workflow_path.read_text().replace(
                'jobs:', '  LEAF_GCP_PROD_BACKEND: object-storage\njobs:')
            workflow_text = workflow_text.replace(
                '      github: ${{ steps.route.outputs.github }}',
                '      github: ${{ steps.route.outputs.github }}\n'
                '      gcp-prod: ${{ steps.route.outputs.gcp-prod }}')
            workflow_text = workflow_text.replace(
                f'          GITHUB_CHANGED: {github_expression}',
                f'          GITHUB_CHANGED: {github_expression}\n'
                f'          LEAF_GCP_PROD_CHANGED: {changed_expression}')
            workflow_text = workflow_text.replace('          github=false', '          github=false\n          leaf_gcp_prod=false')
            workflow_text = workflow_text.replace(
                '          echo "cloudflare=$cloudflare"',
                '          if [ "$LEAF_GCP_PROD_BACKEND" = "object-storage" ] && [ "$LEAF_GCP_PROD_CHANGED" = "true" ]; then\n'
                '            leaf_gcp_prod=true\n          fi\n          echo "cloudflare=$cloudflare"')
            workflow_text = workflow_text.replace(
                '          echo "github=$github" >> "$GITHUB_OUTPUT"',
                '          echo "github=$github" >> "$GITHUB_OUTPUT"\n'
                '          echo "gcp-prod=$leaf_gcp_prod" >> "$GITHUB_OUTPUT"')
            prefix = 'plan' if workflow_name == 'terraform-plan.yml' else 'apply'
            suffix = " && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)" if prefix == 'plan' else ''
            workflow_text += f"\n  {prefix}-gcp-prod:\n    if: needs.changes.outputs.gcp-prod == 'true'{suffix}\n"
            if prefix == 'plan':
                provider_filter = '            gcp-prod:\n' + ''.join(
                    f"              - '{pattern}'\n" for pattern in (
                        'terraform/gcp-prod/**', 'terraform/modules/**', 'mise.toml', 'mise.lock',
                        '.infra-copilot/config.md', '.github/workflows/terraform-*.yml',
                        '.github/scripts/terraform-destroy.cjs'))
                workflow_text = workflow_text.replace('            github:\n', provider_filter + '            github:\n')
                workflow_text = workflow_text.replace(
                    'needs: [changes, plan-cloudflare, plan-github, validate]',
                    'needs: [changes, plan-cloudflare, plan-github, plan-gcp-prod, validate]')
                workflow_text = workflow_text.replace(
                    '          GITHUB_CHANGED: ${{ needs.changes.outputs.github }}',
                    '          GITHUB_CHANGED: ${{ needs.changes.outputs.github }}\n'
                    '          LEAF_GCP_PROD_CHANGED: ${{ needs.changes.outputs.gcp-prod }}')
                workflow_text = workflow_text.replace(
                    '          echo "All plan and validation checks passed."',
                    '          plan_gcp_prod_result=$(echo \'${{ toJson(needs) }}\' | jq -r \'.["plan-gcp-prod"].result // "skipped"\')\n'
                    '          if [ "$LEAF_GCP_PROD_CHANGED" = "true" ] && [ "$plan_gcp_prod_result" != "success" ]; then\n'
                    '            exit 1\n          fi\n          echo "All plan and validation checks passed."')
            workflow_path.write_text(workflow_text)
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 0)
        self.environment['LEAF_BACKENDS'] = '{"github":"object-storage"}'
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 1)

    def test_repository_check_catches_retired_additional_route(self) -> None:
        self.test_additional_provider_workflow_literal_matches_override()
        self.environment.pop('ROUTING_PROVIDER')
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 1)

    def test_quoted_and_flow_environment_overrides_fail_closed(self) -> None:
        for override in ('    env: {GITHUB_BACKEND: hcp}',
                         '    env:\n      "GITHUB_BACKEND": hcp'):
            with self.subTest(override=override):
                self.write_workflows()
                workflow_path = self.checkout / '.github/workflows/terraform-apply.yml'
                workflow_path.write_text(workflow_path.read_text().replace(
                    '  changes:\n', f'  changes:\n{override}\n'))
                self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 2)

    def test_decorative_literal_does_not_prove_execution_routing(self) -> None:
        self.write_workflows()
        workflow_path = self.checkout / '.github/workflows/terraform-apply.yml'
        workflow_path.write_text(workflow_path.read_text().replace(
            'steps.route.outputs.github', 'steps.filter.outputs.github'))
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 1)

    def test_top_level_env_comments_are_supported(self) -> None:
        self.write_workflows()
        for workflow_path in (self.checkout / '.github/workflows').iterdir():
            workflow_path.write_text(workflow_path.read_text().replace('\nenv:\n', '\nenv: # reviewed routes\n'))
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 0)

    def test_unconditional_route_assignment_is_not_supported_evidence(self) -> None:
        self.write_workflows()
        workflow_path = self.checkout / '.github/workflows/terraform-apply.yml'
        workflow_path.write_text(workflow_path.read_text().replace(
            '          github=false', '          github=true'))
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 2)

    def test_empty_bootstrap_inventory_is_not_login_readiness(self) -> None:
        self.environment.update(BACKEND='object-storage', LEAF_BACKENDS='{"gcp":"hcp"}',
                                ADDITIONAL_PROVIDER_NAMES='["gcp"]')
        completed = subprocess.run(
            ['sh', str(REFERENCES / 'checks/hcp-bootstrap-workspaces.sh'), '--login-readiness'],
            cwd=self.checkout, env=self.environment, capture_output=True, text=True,
        )
        self.assertNotEqual(completed.returncode, 0)

    def test_additional_hcp_leaf_requires_actions_validation_when_service_active(self) -> None:
        self.write_workflows()
        (self.checkout / 'terraform/gcp').mkdir(parents=True)
        self.environment.update(NEW_PROVIDER='gcp', HAS_OBJECT_STORAGE='true')
        subprocess.run(['git', 'init', '-q'], cwd=self.checkout, check=True)
        subprocess.run(['git', 'add', '.github'], cwd=self.checkout, check=True)
        subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                        'commit', '-qm', 'workflow fixture'], cwd=self.checkout, check=True)
        manifest_text = (REFERENCES / 'steps.yaml').read_text()
        leaf_body = manifest_text.split('  - id: new-provider-leaf\n')[1].split('  - id: ')[0]
        validation_check = leaf_body.split('    check: |\n')[1].split('      if [ "$NEW_PROVIDER_BACKEND"')[0]
        validation_check = '\n'.join(line.removeprefix('      ') for line in validation_check.splitlines())
        missing = subprocess.run(['sh', '-c', validation_check], cwd=self.checkout,
                                 env=self.environment, capture_output=True, text=True)
        self.assertEqual(missing.returncode, 1)
        workflow_path = self.checkout / '.github/workflows/terraform-plan.yml'
        workflow_path.write_text(workflow_path.read_text().replace('leaf: [cloudflare, github]',
                                                                  'leaf: [cloudflare, github, gcp]'))
        uncommitted = subprocess.run(['sh', '-c', validation_check], cwd=self.checkout,
                                    env=self.environment, capture_output=True, text=True)
        self.assertEqual(uncommitted.returncode, 1)
        subprocess.run(['git', 'add', '.github'], cwd=self.checkout, check=True)
        subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                        'commit', '-qm', 'validation membership'], cwd=self.checkout, check=True)
        included = subprocess.run(['sh', '-c', validation_check], cwd=self.checkout,
                                  env=self.environment, capture_output=True, text=True)
        self.assertEqual(included.returncode, 0, included.stderr)

    def test_digit_leading_provider_uses_shell_safe_prefixed_variables(self) -> None:
        self.test_additional_provider_workflow_literal_matches_override()
        self.environment.update(ADDITIONAL_PROVIDER_NAMES='["1password"]', ROUTING_PROVIDER='1password',
                                LEAF_BACKENDS='{"github":"object-storage","1password":"object-storage"}')
        for workflow_path in (self.checkout / '.github/workflows').iterdir():
            workflow_text = workflow_path.read_text().replace('gcp-prod', '1password').replace(
                'LEAF_GCP_PROD', 'LEAF_1PASSWORD').replace('leaf_gcp_prod', 'leaf_1password')
            workflow_text = workflow_text.replace('plan_gcp_prod_result', 'plan_1password_result').replace(
                '.outputs.1password', ".outputs['1password']")
            workflow_path.write_text(workflow_text)
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 0)

    def test_blank_line_cannot_hide_a_later_route_override(self) -> None:
        self.write_workflows()
        workflow_path = self.checkout / '.github/workflows/terraform-apply.yml'
        workflow_path.write_text(workflow_path.read_text().replace(
            '          echo "github=$github" >> "$GITHUB_OUTPUT"',
            '          echo "github=$github" >> "$GITHUB_OUTPUT"\n\n'
            '          cloudflare=true\n          echo "cloudflare=$cloudflare" >> "$GITHUB_OUTPUT"'))
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 2)

    def test_crlf_templates_preserve_routing_semantics(self) -> None:
        self.write_workflows()
        for workflow_path in (self.checkout / '.github/workflows').iterdir():
            workflow_path.write_bytes(workflow_path.read_bytes().replace(b'\n', b'\r\n'))
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 0)

    def test_missing_workflows_and_new_routes_are_provisioning_failures(self) -> None:
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 1)
        self.write_workflows()
        self.environment.update(ADDITIONAL_PROVIDER_NAMES='["gcp"]',
                                LEAF_BACKENDS='{"github":"object-storage","gcp":"object-storage"}')
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 1)

    def test_escaped_environment_and_quoted_job_keys_are_unsupported(self) -> None:
        for injection in ('        env:\n          "\\u0043LOUDFLARE_BACKEND": object-storage\n',
                          '  "plan-gcp":\n    if: true\n'):
            with self.subTest(injection=injection):
                self.write_workflows()
                workflow_path = self.checkout / '.github/workflows/terraform-plan.yml'
                workflow_path.write_text(workflow_path.read_text() + injection)
                self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 2)

    def test_route_in_an_unrelated_job_is_not_changes_evidence(self) -> None:
        self.write_workflows()
        workflow_path = self.checkout / '.github/workflows/terraform-apply.yml'
        workflow_text = workflow_path.read_text()
        route_start = workflow_text.index('      - name: Route object-storage leaves')
        route_end = workflow_text.index('  apply-cloudflare:')
        route_block = workflow_text[route_start:route_end]
        workflow_text = workflow_text[:route_start] + workflow_text[route_end:]
        workflow_text += '  decoy:\n    steps:\n' + route_block
        workflow_path.write_text(workflow_text)
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 1)

    def test_additional_plan_must_be_in_the_required_aggregate(self) -> None:
        self.test_additional_provider_workflow_literal_matches_override()
        self.environment['LEAF_BACKENDS'] = '{"github":"object-storage","gcp-prod":"object-storage"}'
        workflow_path = self.checkout / '.github/workflows/terraform-plan.yml'
        workflow_path.write_text(workflow_path.read_text().replace('plan-github, plan-gcp-prod, validate',
                                                                  'plan-github, validate'))
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 1)

    def test_provider_keys_with_bootstrap_suffixes_are_distinct(self) -> None:
        self.test_additional_provider_workflow_literal_matches_override()
        self.environment.update(ADDITIONAL_PROVIDER_NAMES='["org-github"]', ROUTING_PROVIDER='org-github',
                                LEAF_BACKENDS='{"github":"object-storage","org-github":"object-storage"}')
        for workflow_path in (self.checkout / '.github/workflows').iterdir():
            workflow_path.write_text(workflow_path.read_text().replace('gcp-prod', 'org-github').replace(
                'GCP_PROD', 'ORG_GITHUB').replace('gcp_prod', 'org_github'))
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 0)

    def test_active_leaf_requires_its_concrete_filter_and_shared_inputs(self) -> None:
        for mutation in ('missing-leaf', 'missing-lock'):
            with self.subTest(mutation=mutation):
                self.write_workflows()
                workflow_path = self.checkout / '.github/workflows/terraform-plan.yml'
                workflow_text = workflow_path.read_text()
                if mutation == 'missing-leaf':
                    workflow_text = re.sub(r'^            github:\n(?:              .*\n)+', '', workflow_text, flags=re.M)
                else:
                    workflow_text = workflow_text.replace("              - 'mise.lock'\n", '')
                workflow_path.write_text(workflow_text)
                self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 1)

    def prepare_hcp_api(self, *, legacy_permissions: dict[str, bool] | None = None) -> None:
        self.environment.update(ORG='acme', REPO='acme/infra', TERRAFORM_VERSION='1.15.0',
                                hcp_api='https://app.terraform.io/api/v2',
                                HCP_TOKEN='plan-token', TF_TOKEN_app_terraform_io='plan-token')
        binary_directory = self.checkout / 'bin'
        binary_directory.mkdir()
        workspace_data = []
        for leaf_name, workspace_name in (('cloudflare', 'cloudflare'), ('github', 'github-org')):
            attributes = {
                'name': workspace_name, 'working-directory': f'terraform/{leaf_name}',
                'execution-mode': 'remote', 'terraform-version': '1.15.0', 'auto-apply': False,
                'auto-destroy-at': None, 'auto-destroy-activity-duration': None,
                'speculative-enabled': True, 'file-triggers-enabled': True,
                'trigger-patterns': [f'terraform/{leaf_name}/**', 'terraform/modules/**',
                                     '.infra-copilot/config.md', 'mise.toml'],
                'vcs-repo': {'identifier': 'acme/infra', 'branch': 'main'},
                'permissions': {'can-queue-run': True, 'can-queue-apply': False, 'can-update': False},
            }
            if leaf_name == 'github' and legacy_permissions is not None:
                attributes['permissions'] = legacy_permissions
            workspace_data.append({'id': f'ws-{workspace_name}', 'attributes': attributes})
            (self.checkout / f'{workspace_name}.json').write_text(json.dumps({'data': workspace_data[-1]}))
            leaf_directory = self.checkout / f'terraform/{leaf_name}'
            leaf_directory.mkdir(parents=True)
            (leaf_directory / 'versions.tf').write_text(
                f'terraform {{ cloud {{ organization = "acme" workspaces {{ name = "{workspace_name}" }} }} }}\n',
            )
        (self.checkout / 'api.json').write_text(json.dumps({
            'data': workspace_data, 'meta': {'pagination': {'total-pages': 1}},
        }))
        curl_path = binary_directory / 'curl'
        curl_path.write_text('''#!/bin/sh
for argument in "$@"; do
  case "$argument" in
    */account/details) printf '404'; exit 0 ;;
    */workspaces/cloudflare) cat cloudflare.json; exit 0 ;;
    */workspaces/github-org) echo 'MIGRATED WORKSPACE QUERIED' >&2; exit 22 ;;
    */workspaces\\?*) cat api.json; exit 0 ;;
  esac
done
exit 22
''')
        curl_path.chmod(0o755)
        self.environment['PATH'] = f'{binary_directory}{os.pathsep}{os.environ["PATH"]}'

    def test_bootstrap_never_queries_migrated_workspace(self) -> None:
        self.prepare_hcp_api()
        completed = self.execute_check('hcp-bootstrap-workspaces.sh')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn('MIGRATED', completed.stderr)

    def test_legacy_read_only_workspace_needs_no_regrant(self) -> None:
        self.prepare_hcp_api(legacy_permissions={
            'can-queue-run': False, 'can-queue-apply': False, 'can-update': False,
        })
        completed = self.execute_check('hcp-apply-scope.sh')
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_migration_does_not_hide_legacy_apply_capability(self) -> None:
        self.prepare_hcp_api(legacy_permissions={
            'can-queue-run': True, 'can-queue-apply': True, 'can-update': False,
        })
        completed = self.execute_check('hcp-apply-scope.sh')
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn('UNPROTECTED', completed.stderr)
        self.assertIn('github-org', completed.stderr)
