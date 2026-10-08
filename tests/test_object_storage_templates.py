"""Execute the shipped state guard and plan-comment scripts without cloud access."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REFERENCES = Path(__file__).resolve().parents[1] / '.ai-rulez/skills/infra-copilot/references'


@unittest.skipUnless(os.name == 'posix', 'state guard requires POSIX shell')
class ApplyGuardTests(unittest.TestCase):
    def test_guard_refuses_empty_and_unreadable_state(self) -> None:
        template = (REFERENCES / 'templates/terraform-apply.yml').read_text()
        for leaf in ('cloudflare', 'github'):
            block = template.split(f'working-directory: terraform/{leaf}\n', 2)[2]
            script = textwrap.dedent(block.split('        run: |\n', 1)[1]
                                     .split('\n      - name:', 1)[0])
            for state, status, opt_out, expected in (
                ('', 0, '', 1),
                ('', 0, 'false', 1),
                ('', 0, 'TRUE', 1),
                ('', 0, 'true', 0),
                ('github_repository.infra', 0, '', 0),
                ('', 1, '', 1),
                ('', 1, 'true', 1),
                ('partial.output', 1, 'true', 1),
            ):
                with self.subTest(leaf=leaf, state=state, status=status, opt_out=opt_out):
                    result = subprocess.run(
                        ['bash', '-eu', '-o', 'pipefail', '-c',
                         'terraform() { printf "%s" "$TEST_STATE"; return "$TEST_STATUS"; }\n'
                         + script],
                        env={**os.environ, 'TEST_STATE': state, 'TEST_STATUS': str(status),
                             'ALLOW_EMPTY_STATE': opt_out},
                        capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, expected, result.stderr)


class PlanCommentTests(unittest.TestCase):
    def test_create_then_update_only_owned_leaf_comment(self) -> None:
        template = (REFERENCES / 'templates/terraform-plan.yml').read_text()
        scripts = re.findall(r'          script: \|\n(.*?)(?=\n      - name:)', template, re.S)
        self.assertEqual(len(scripts), 2)
        for leaf, script in zip(('cloudflare', 'github'), scripts):
            script = textwrap.dedent(script)
            with self.subTest(leaf=leaf), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = root / 'terraform' / leaf / 'plan.txt'
                plan.parent.mkdir(parents=True)
                plan.write_text('No changes.')
                # paginate supplies comments beyond page one; spoofed markers and other
                # leaves must not be selected. Reject dropped await calls too.
                harness = '''
const assert = require('node:assert/strict');
const leaf = LEAF;
const marker = `<!-- infra-copilot-plan:${leaf} -->`;
const context = { repo: { owner: 'owner', repo: 'infra' }, issue: { number: 107 } };
const comments = [
  { id: 1, body: `${marker}\\nspoof`, user: { login: 'contributor' } },
  { id: 2, body: '<!-- infra-copilot-plan:other -->', user: { login: 'github-actions[bot]' } },
  { id: 3, body: null, user: { login: 'github-actions[bot]' } }
];
let calls = [];
const github = {
  rest: { issues: {
    listComments: () => {},
    createComment: async args => {
      await new Promise(resolve => setTimeout(resolve, 5));
      assert.equal(args.issue_number, 107);
      calls.push(['create', args]);
      comments.push({ id: 4, body: args.body, user: { login: 'github-actions[bot]' } });
    },
    updateComment: async args => {
      await new Promise(resolve => setTimeout(resolve, 5));
      assert.equal(args.comment_id, 4);
      calls.push(['update', args]);
    }
  } },
  paginate: async (method, args) => {
    assert.equal(method, github.rest.issues.listComments);
    assert.equal(args.per_page, 100);
    assert.equal(args.issue_number, 107);
    return comments;
  }
};
async function post() {
SCRIPT
}
(async () => {
  await post();
  assert.equal(calls.length, 1);
  await post();
  assert.deepEqual(calls.map(call => call[0]), ['create', 'update']);
  for (const [, args] of calls) {
    assert.equal(args.owner, 'owner');
    assert.equal(args.repo, 'infra');
    assert.ok(args.body.startsWith(marker + '\\n'));
    assert.ok(args.body.includes('No changes.'));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
'''.replace('LEAF', json.dumps(leaf)).replace('SCRIPT', script)
                result = subprocess.run(['node', '-e', harness], cwd=root,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
