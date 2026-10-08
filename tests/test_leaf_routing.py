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
                f'env:\n  CLOUDFLARE_BACKEND: {cloudflare_backend}\n  GITHUB_BACKEND: {github_backend}\njobs:\n',
                encoding='utf-8',
            )

    def test_static_workflows_must_agree_with_effective_not_default(self) -> None:
        self.write_workflows()
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 0)
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
            workflow_path.write_text(workflow_path.read_text().replace(
                'jobs:', '  GCP_PROD_BACKEND: object-storage\njobs:'))
        self.assertEqual(self.execute_check('workflow-routing.sh').returncode, 0)
        self.environment['LEAF_BACKENDS'] = '{"github":"object-storage"}'
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
