"""The phase-5 `template-adopt` step: adopt the Template into an existing repo.

The check is the same committed-answers-plus-Config-block predicate `template-render`
uses, so it has to read red on a repo that pre-dates the Template and green once the
adoption is committed. The procedure is prose, so the tests pin the properties that
keep it from overwriting a human's files.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / '.ai-rulez/skills/infra/references'
STEPS = REFERENCES / 'steps.yaml'
IMPORT_DOC = REFERENCES / 'docs/import.md'
IMPORT_SKILL = ROOT / '.ai-rulez/skills/infra-import/SKILL.md'


def step(step_id: str) -> str:
    text = STEPS.read_text(encoding='utf-8')
    matches = list(re.finditer(r'^  - id: (\S+)\n', text, re.MULTILINE))
    for index, match in enumerate(matches):
        if match.group(1) == step_id:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            return text[match.start():end]
    raise AssertionError(f'{step_id} is not in the manifest')


def folded_check(body: str) -> str:
    match = re.search(r'^    check: >-\n(?P<body>(?:      .*\n)+)', body, re.MULTILINE)
    if match is None:
        raise AssertionError('step has no folded check')
    return ' '.join(line.strip() for line in match.group('body').splitlines())


class AdoptStepManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.body = step('template-adopt')
        self.flat = re.sub(r'\s+', ' ', self.body)

    def test_it_is_a_phase_five_agent_step_before_the_discovery_token(self) -> None:
        self.assertIn('    phase: 5\n', self.body)
        self.assertIn('    actor: AGENT\n', self.body)
        text = STEPS.read_text(encoding='utf-8')
        self.assertLess(text.index('id: template-adopt'), text.index('id: migrate-discovery-token'))

    def test_it_shares_the_render_check(self) -> None:
        self.assertEqual(folded_check(self.body), folded_check(step('template-render')))

    def test_it_never_renders_into_the_repo_or_overwrites(self) -> None:
        self.assertIn('never `copier copy` into the repo itself', self.flat)
        self.assertIn('scratch directory', self.flat)
        self.assertIn('never overwriting on your own', self.flat)
        self.assertIn('docs/import.md#adopt-the-template-first', self.body)

    def test_the_import_skill_scans_it_first(self) -> None:
        skill = re.sub(r'\s+', ' ', IMPORT_SKILL.read_text(encoding='utf-8'))
        self.assertIn('`template-adopt`, `template-contract`, `migrate-discovery-token` and `migrate-import`', skill)
        self.assertIn('those four steps only', skill)

    def test_the_runbook_covers_the_old_template_and_the_copy_trap(self) -> None:
        doc = re.sub(r'\s+', ' ', IMPORT_DOC.read_text(encoding='utf-8'))
        self.assertIn('## Adopt the Template first', doc)
        self.assertIn('`infra-template` GitHub template', doc)
        self.assertIn('`.infra-copilot/`', doc)
        self.assertIn('### Fixture run', doc)
        self.assertIn('`copier copy` straight into the repo is the wrong move', doc)
        self.assertIn('`gh:hasansezertasan/copier-infra`', doc)


@unittest.skipUnless(os.name == 'posix' and shutil.which('sh'), 'POSIX shell required')
class AdoptCheckTests(unittest.TestCase):
    ANSWERS = '_commit: v0.1.0\n_src_path: gh:hasansezertasan/copier-infra\nbackend: hcp\n'
    README = ('# my infra\n\nhand written\n\n<!-- infra:config start -->\n```yaml\n```\n'
              '<!-- infra:config end -->\n')

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.git('init', '-q')
        (self.repo / 'README.md').write_text('# my infra\n\nhand written\n', encoding='utf-8')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'old')
        self.check = folded_check(step('template-adopt'))

    def git(self, *args: str) -> None:
        subprocess.run(
            ['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com',
             '-c', 'commit.gpgsign=false', *args],
            cwd=self.repo, check=True, capture_output=True,
        )

    def run_check(self) -> int:
        env = {**os.environ, 'INFRA_REFERENCES': str(REFERENCES)}
        return subprocess.run(['sh', '-c', self.check], cwd=self.repo, env=env,
                              capture_output=True).returncode

    def adopt(self, *, answers: str, readme: str, commit: bool = True) -> None:
        (self.repo / '.copier-answers.yml').write_text(answers, encoding='utf-8')
        (self.repo / 'README.md').write_text(readme, encoding='utf-8')
        if commit:
            self.git('add', '-A')
            self.git('commit', '-q', '-m', 'adopt')

    def test_a_repo_that_predates_the_template_is_red(self) -> None:
        self.assertNotEqual(self.run_check(), 0)

    def test_a_committed_adoption_is_green(self) -> None:
        self.adopt(answers=self.ANSWERS, readme=self.README)
        self.assertEqual(self.run_check(), 0)

    def test_an_uncommitted_adoption_is_red(self) -> None:
        self.adopt(answers=self.ANSWERS, readme=self.README, commit=False)
        self.assertNotEqual(self.run_check(), 0)

    def test_answers_from_a_scratch_path_are_red(self) -> None:
        self.adopt(answers=self.ANSWERS.replace('gh:hasansezertasan/copier-infra', '/scratch/render'),
                   readme=self.README)
        self.assertNotEqual(self.run_check(), 0)

    def test_a_missing_config_block_is_red(self) -> None:
        self.adopt(answers=self.ANSWERS, readme='# my infra\n')
        self.assertNotEqual(self.run_check(), 0)


if __name__ == '__main__':
    unittest.main()
