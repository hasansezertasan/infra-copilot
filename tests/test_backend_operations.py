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
        for reference in ('$BACKEND', '${BACKEND}', 'HCP', 'GitHub Actions', 'object-storage'):
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

    def test_backend_gate_must_match_implementation(self) -> None:
        text = self.manifest.read_text(encoding='utf-8').replace('    implementation: hcp\n', '    implementation: object-storage\n', 1)
        self.manifest.write_text(text, encoding='utf-8')
        self.assertTrue(any('selector lacks its backend gate' in e for e in validate_backend_operations(self.root)))

    def test_not_applicable_cannot_be_unexplained(self) -> None:
        text = self.manifest.read_text(encoding='utf-8')
        text = re.sub(r'    not_applicable: .*', '    not_applicable: ""', text, count=1)
        self.manifest.write_text(text, encoding='utf-8')
        self.assertTrue(any('backend-specific reason' in e for e in validate_backend_operations(self.root)))


if __name__ == '__main__':
    unittest.main()
