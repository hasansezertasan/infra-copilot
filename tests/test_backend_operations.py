"""Regression gates for backend-neutral skills and complete operation coverage."""
from __future__ import annotations

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

    def test_router_cannot_select_backend(self) -> None:
        for reference in ('$BACKEND', '${BACKEND}', 'HCP', 'GitHub Actions', 'object-storage'):
            with self.subTest(reference=reference):
                skill = self.root / '.ai-rulez/skills/add/SKILL.md'
                original = skill.read_text()
                skill.write_text(original + '\n' + reference + '\n')
                self.assertTrue(any('skill outside setup' in e for e in validate_backend_operations(self.root)))
                skill.write_text(original)

    def test_new_skill_is_also_checked(self) -> None:
        skill = self.root / '.ai-rulez/skills/retire/SKILL.md'
        skill.parent.mkdir()
        skill.write_text('Use $BACKEND to choose execution.\n')
        self.assertTrue(any('retire/SKILL.md' in e for e in validate_backend_operations(self.root)))

    def test_missing_operation_is_rejected(self) -> None:
        self.manifest.write_text(self.manifest.read_text().replace('    operation: plan-cloudflare\n', '', 1))
        self.assertTrue(any('needs an operation' in e for e in validate_backend_operations(self.root)))

    def test_missing_backend_coverage_is_rejected(self) -> None:
        text = self.manifest.read_text()
        a = text.index('  - id: plan-cloudflare-gha\n')
        b = text.index('  - id: ', a + 1)
        self.manifest.write_text(text[:a] + text[b:])
        self.assertTrue(any('plan-cloudflare: missing implementation' in e for e in validate_backend_operations(self.root)))

    def test_backend_gate_must_match_implementation(self) -> None:
        text = self.manifest.read_text().replace('    implementation: hcp\n', '    implementation: object-storage\n', 1)
        self.manifest.write_text(text)
        self.assertTrue(any('selector lacks its backend gate' in e for e in validate_backend_operations(self.root)))

    def test_not_applicable_cannot_be_unexplained(self) -> None:
        text = self.manifest.read_text()
        import re
        text = re.sub(r'    not_applicable: .*', '    not_applicable: ""', text, count=1)
        self.manifest.write_text(text)
        self.assertTrue(any('backend-specific reason' in e for e in validate_backend_operations(self.root)))


if __name__ == '__main__':
    unittest.main()
