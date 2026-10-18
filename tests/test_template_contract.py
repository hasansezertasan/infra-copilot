"""Run the Template contract check against a temp repo's recorded Template version.

The check reads `_commit` from `.copier-answers.yml` and compares it with the minimum
release tag. Exit 0 passes, 1 means an older tag (propose the Template's update) and
2 means the version cannot be judged (hand off, never guess).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / '.ai-rulez/skills/infra/references/checks/template-contract.sh'


@unittest.skipUnless(os.name == 'posix' and shutil.which('sh'), 'POSIX shell required')
class TemplateContractTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.checkout = Path(temporary.name)

    def run_check(self, commit: str | None, minimum: str = 'v0.2.0') -> subprocess.CompletedProcess[str]:
        if commit is not None:
            (self.checkout / '.copier-answers.yml').write_text(
                f'_commit: {commit}\n_src_path: gh:hasansezertasan/copier-infra\nbackend: hcp\n',
                encoding='utf-8',
            )
        return subprocess.run(
            ['sh', str(CHECK), minimum], cwd=self.checkout, capture_output=True, text=True,
        )

    def test_tag_at_the_minimum_passes(self) -> None:
        self.assertEqual(self.run_check('v0.2.0').returncode, 0)

    def test_tag_above_the_minimum_passes_by_semantic_version(self) -> None:
        # 0.10.0 is above 0.2.0 numerically, though it sorts below it as text.
        self.assertEqual(self.run_check('v0.10.0').returncode, 0)

    def test_quoted_tag_passes(self) -> None:
        self.assertEqual(self.run_check('"v1.0.0"').returncode, 0)

    def test_another_templates_answers_file_is_indeterminate(self) -> None:
        self.run_check('v1.0.0')
        answers = self.checkout / '.copier-answers.yml'
        answers.write_text(
            answers.read_text(encoding='utf-8').replace('hasansezertasan/copier-infra', 'someone/other'),
            encoding='utf-8',
        )
        self.assertEqual(self.run_check(None).returncode, 2)

    def test_source_must_be_an_exact_alias_not_a_substring(self) -> None:
        for crafted in ('gh:attacker/hasansezertasan/copier-infra',
                        'gh:someone/evil # gh:hasansezertasan/copier-infra',
                        'gh:hasansezertasan/copier-infra-fork'):
            with self.subTest(crafted=crafted):
                (self.checkout / '.copier-answers.yml').write_text(
                    f'_commit: v1.0.0\n_src_path: {crafted}\n', encoding='utf-8')
                self.assertEqual(self.run_check(None).returncode, 2)

    def test_canonical_aliases_pass(self) -> None:
        for alias in ('gh:hasansezertasan/copier-infra.git', '"https://github.com/hasansezertasan/copier-infra"',
                      'git@github.com:hasansezertasan/copier-infra.git # pinned'):
            with self.subTest(alias=alias):
                (self.checkout / '.copier-answers.yml').write_text(
                    f'_commit: v1.0.0\n_src_path: {alias}\n', encoding='utf-8')
                self.assertEqual(self.run_check(None).returncode, 0)

    def test_source_only_skips_the_version_comparison(self) -> None:
        self.run_check('v0.0.1')
        completed = subprocess.run(['sh', str(CHECK), '--source-only'], cwd=self.checkout,
                                   capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0)

    def test_trailing_comment_and_crlf_are_ignored(self) -> None:
        self.assertEqual(self.run_check('v0.2.0 # pinned\r').returncode, 0)

    def test_ambient_override_is_ignored(self) -> None:
        os.environ['TEMPLATE_MIN_TAG'] = 'v0.0.1'
        self.addCleanup(os.environ.pop, 'TEMPLATE_MIN_TAG')
        self.assertEqual(self.run_check('v0.1.9').returncode, 1)

    def test_older_tag_proposes_the_templates_update(self) -> None:
        completed = self.run_check('v0.1.9')
        self.assertEqual(completed.returncode, 1)
        self.assertIn('copier update', completed.stderr)

    def test_bare_commit_is_indeterminate(self) -> None:
        completed = self.run_check('4f2a9c1d7e3b5a6c8d9e0f1a2b3c4d5e6f708192')
        self.assertEqual(completed.returncode, 2)
        self.assertIn('hand off', completed.stderr)

    def test_between_tags_value_is_indeterminate(self) -> None:
        self.assertEqual(self.run_check('v0.3.0-3-gabc1234').returncode, 2)

    def test_missing_answers_file_is_indeterminate(self) -> None:
        self.assertEqual(self.run_check(None).returncode, 2)


if __name__ == '__main__':
    unittest.main()
