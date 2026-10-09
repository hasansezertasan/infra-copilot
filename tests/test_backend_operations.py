"""Regression gates for backend-neutral skills and complete operation coverage."""
from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate import validate_backend_operations

ROOT = Path(__file__).resolve().parents[1]


class BackendOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / '.ai-rulez', self.root / '.ai-rulez')
        self.manifest = self.root / '.ai-rulez/skills/infra-copilot/references/steps.yaml'

    def test_current_contracts_are_complete(self) -> None:
        self.assertEqual(validate_backend_operations(self.root), [])

    def test_credential_refresh_is_member_scoped(self) -> None:
        text = self.manifest.read_text(encoding='utf-8')
        login = text.split('  - id: hcp-login\n', 1)[1].split('  - id: ', 1)[0]
        self.assertIn('    refresh_credentials: true', login)
        protocol = self.manifest.with_name('protocol.md').read_text(encoding='utf-8')
        self.assertIn('before evaluating the next member, even if its operation is not yet green', protocol)

    def test_cutover_contract_preserves_human_transfer_and_retirement_gates(self) -> None:
        text = self.manifest.read_text(encoding='utf-8')
        member = text.split('  - id: backend-config\n', 1)[1].split('  - id: ', 1)[0]
        run_contract = member.split('    run: |\n', 1)[1].split('    check:', 1)[0]
        for required in ('OBJECT_STORAGE_BOOTSTRAP_LEAVES',
                         'docs/object-storage-state.md#migrating-from-hcp',
                         "human locks that leaf's HCP workspace before pulling state",
                         'uploads without overwriting', 'bytes, serial, lineage',
                         'membership BEFORE merging', 'discard/cancel actions',
                         'without revoking credentials still needed by HCP-routed leaves'):
            self.assertIn(required, run_contract)
        self.assertNotIn('terraform state pull', run_contract)
        self.assertNotIn('terraform init -migrate-state', run_contract)

    def test_staged_config_contracts_support_effective_leaf_routes(self) -> None:
        for document in ('config.md', 'config.md.example'):
            with self.subTest(document=document):
                contract = self.manifest.with_name(document).read_text(encoding='utf-8')
                staged = contract.split('## Staged backend migration\n', 1)[1]
                self.assertIn('leaf_backends', staged)
                self.assertNotIn('per-leaf overrides are not supported', contract)
                self.assertNotIn('until the last leaf moves', contract)
                self.assertIn('state transfer', staged.replace('state-transfer', 'state transfer'))

    def test_relocated_runbook_links_resolve_to_sections(self) -> None:
        references = self.manifest.parent
        runbooks = {'ci.md', 'state.md', 'secrets.md', 'hcp-ci.md', 'hcp-state.md',
                    'hcp-secrets.md', 'object-storage-ci.md', 'object-storage-state.md'}
        checked = 0
        for source in [*references.rglob('*.md'), self.manifest]:
            for match in re.finditer(r'([./a-zA-Z0-9_-]+\.md)#([a-zA-Z0-9_-]+)', source.read_text(encoding='utf-8')):
                target = (source.parent / match[1]).resolve()
                if target.name not in runbooks:
                    continue
                self.assertTrue(target.is_file(), str(target))
                anchors = {re.sub(r'[^\w -]', '', heading.lower()).replace(' ', '-')
                           for heading in re.findall(r'^#{1,6} (.+)$', target.read_text(encoding='utf-8'), re.M)}
                self.assertIn(match[2], anchors, f'{source.name}: {match[0]} has no target section')
                checked += 1
        self.assertGreater(checked, 10)

    def test_router_cannot_select_backend(self) -> None:
        for reference in ('$BACKEND', '${BACKEND}', 'HCP', 'GitHub Actions', 'object-storage',
                            '$HAS_HCP_BOOTSTRAP', '$HAS_OBJECT_STORAGE_BOOTSTRAP',
                            '$HCP_LEAVES', '$OBJECT_STORAGE_LEAVES'):
            with self.subTest(reference=reference):
                skill = self.root / '.ai-rulez/skills/add/SKILL.md'
                original = skill.read_text(encoding='utf-8')
                skill.write_text(original + '\n' + reference + '\n', encoding='utf-8')
                self.assertTrue(any('skill outside setup' in e for e in validate_backend_operations(self.root)))
                skill.write_text(original, encoding='utf-8')

    def test_new_skill_is_also_checked(self) -> None:
        skill = self.root / '.ai-rulez/skills/retire/SKILL.md'
        skill.parent.mkdir()
        skill.write_text('Use $BACKEND to choose execution.\n', encoding='utf-8')
        self.assertTrue(any(str(Path('retire/SKILL.md')) in e for e in validate_backend_operations(self.root)))

    def test_missing_operation_is_rejected(self) -> None:
        self.manifest.write_text(self.manifest.read_text(encoding='utf-8').replace('    operation: plan-cloudflare\n', '', 1), encoding='utf-8')
        self.assertTrue(any('needs an operation' in e for e in validate_backend_operations(self.root)))

    def test_missing_backend_coverage_is_rejected(self) -> None:
        text = self.manifest.read_text(encoding='utf-8')
        a = text.index('  - id: plan-cloudflare-gha\n')
        b = text.index('  - id: ', a + 1)
        self.manifest.write_text(text[:a] + text[b:], encoding='utf-8')
        self.assertTrue(any('plan-cloudflare: missing implementation' in e for e in validate_backend_operations(self.root)))

    def test_inventory_operation_without_members_is_rejected(self) -> None:
        text = self.manifest.read_text(encoding='utf-8')
        text = re.sub(r'^  - id: [^\n]+\n.*?(?=^  - id: |\Z)',
                      lambda match: '' if '    operation: plan-cloudflare\n' in match[0] else match[0],
                      text, flags=re.M | re.S)
        self.manifest.write_text(text, encoding='utf-8')
        self.assertTrue(any('plan-cloudflare: missing implementation' in error
                            for error in validate_backend_operations(self.root)))

    def test_backend_gate_must_match_implementation(self) -> None:
        text = self.manifest.read_text(encoding='utf-8').replace('    implementation: hcp\n', '    implementation: object-storage\n', 1)
        self.manifest.write_text(text, encoding='utf-8')
        self.assertTrue(any('selector lacks its backend gate' in e for e in validate_backend_operations(self.root)))

    def test_repository_default_cannot_replace_leaf_route(self) -> None:
        text = self.manifest.read_text(encoding='utf-8').replace(
            '[ "$GITHUB_BACKEND" = "object-storage" ]', '[ "$BACKEND" = "object-storage" ]', 1)
        self.manifest.write_text(text, encoding='utf-8')
        self.assertTrue(any('gh-app-gha: implementation selector lacks' in error
                            for error in validate_backend_operations(self.root)))

    def test_protection_cannot_follow_github_management_leaf(self) -> None:
        text = self.manifest.read_text(encoding='utf-8')
        offset = text.index('  - id: status-check-context\n')
        text = text[:offset] + text[offset:].replace(
            '[ "$HAS_HCP" = "true" ]', '[ "$GITHUB_BACKEND" = "hcp" ]', 1)
        self.manifest.write_text(text, encoding='utf-8')
        self.assertTrue(any('status-check-context: implementation selector lacks' in error
                            for error in validate_backend_operations(self.root)))

    def test_shared_runtime_branch_cannot_use_repository_default(self) -> None:
        text = self.manifest.read_text(encoding='utf-8').replace(
            'if [ "$CLOUDFLARE_BACKEND" = "object-storage" ]; then',
            'if [ "$BACKEND" = "object-storage" ]; then', 1)
        self.manifest.write_text(text, encoding='utf-8')
        self.assertTrue(any('migrate-import: runtime routing must use effective' in error
                            for error in validate_backend_operations(self.root)))

    def test_not_applicable_cannot_be_unexplained(self) -> None:
        text = self.manifest.read_text(encoding='utf-8')
        text = re.sub(r'    not_applicable: .*', '    not_applicable: ""', text, count=1)
        self.manifest.write_text(text, encoding='utf-8')
        self.assertTrue(any('backend-specific reason' in e for e in validate_backend_operations(self.root)))

    def test_gha_wif_guidance_and_trust_conditions(self) -> None:
        doc = (self.root / '.ai-rulez/skills/infra-copilot/references/docs/object-storage-ci.md').read_text(encoding='utf-8')
        self.assertIn('### GCP Workload Identity Federation', doc)
        self.assertIn('assertion.repository_id', doc)
        self.assertIn('assertion.repository_owner_id', doc)
        self.assertIn("assertion.ref == 'refs/heads/main'", doc)
        self.assertIn("assertion.environment == 'production'", doc)
        self.assertIn('!has(assertion.environment)', doc)
        self.assertIn('One dedicated pool per repository', doc)
        self.assertIn('gha_mapping_plan = {', doc)
        self.assertIn('gha_mapping_apply = {', doc)
        self.assertIn('"google.subject"                = "assertion.repository_id"', doc)

        manifest = self.manifest.read_text(encoding='utf-8')
        self.assertIn('docs: docs/object-storage-ci.md#gcp-workload-identity-federation', manifest)
        self.assertIn('--env production', manifest)

        gcp_doc = (self.root / '.ai-rulez/skills/infra-copilot/references/gcp.md').read_text(encoding='utf-8')
        self.assertIn('docs/object-storage-ci.md#gcp-workload-identity-federation', gcp_doc)


if __name__ == '__main__':
    unittest.main()
