"""Run the shipped helper's cloud-free behavior suite on every supported host."""
from __future__ import annotations

import subprocess
import os
import re
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DestructiveApplyTests(unittest.TestCase):
    def test_shipped_helper_behavior(self) -> None:
        result = subprocess.run(
            ['node', '--test', 'tests/terraform-destroy.test.cjs'], cwd=ROOT,
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


@unittest.skipUnless(os.name == 'posix', 'label resume check requires POSIX shell')
class DestructiveLabelTests(unittest.TestCase):
    def test_label_and_locked_decision_are_both_required(self) -> None:
        manifest = (ROOT / '.ai-rulez/skills/infra-copilot/references/steps.yaml').read_text()
        body = manifest.split('  - id: gha-destroy-label\n', 1)[1].split('\n  - id:', 1)[0]
        match = re.search(r'^    check: \|\n((?:      .*\n|\n)+)', body, re.M)
        script = textwrap.dedent(match.group(1))
        for labels, api_status, decision, expected in (
            ('allow-destroy', 0, '| Destructive apply | allow-destroy | locked | Intent only |', 0),
            ('', 0, '| Destructive apply | allow-destroy | locked | Intent only |', 1),
            ('allow-destroy', 1, '| Destructive apply | allow-destroy | locked | Intent only |', 2),
            ('allow-destroy', 0, '| Destructive apply | allow-destroy | proposed | Intent only |', 1),
            ('allow-destroy', 0, '', 1),
        ):
            with self.subTest(labels=labels, api_status=api_status, decision=decision):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / '.infra-copilot').mkdir()
                    (root / '.infra-copilot/decisions.md').write_text(decision)
                    result = subprocess.run(
                        ['sh', '-c', 'gh() { printf "%s" "$TEST_LABELS"; return "$TEST_STATUS"; }\n' + script],
                        cwd=root, capture_output=True, text=True,
                        env={**os.environ, 'REPO': 'owner/repo', 'TEST_LABELS': labels, 'TEST_STATUS': str(api_status)},
                    )
                    self.assertEqual(result.returncode, expected, result.stderr)
