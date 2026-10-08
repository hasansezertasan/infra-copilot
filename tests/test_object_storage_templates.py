"""Execute the shipped state guard and plan-comment scripts without cloud access."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REFERENCES = Path(__file__).resolve().parents[1] / '.ai-rulez/skills/infra-copilot/references'


@unittest.skipUnless(os.name == 'posix', 'state guard requires POSIX shell')
class ApplyGuardTests(unittest.TestCase):
    def test_guard_requires_state_unless_first_creation_is_authorized(self) -> None:
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
                ('', 1, 'true', 0),
                ('partial.output', 1, 'true', 0),
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
const context = { repo: { owner: 'owner', repo: 'infra' }, issue: { number: 107 },
  payload: { pull_request: { head: { sha: 'current-head' } } } };
const core = { notice: () => {} };
const comments = [
  { id: 1, body: `${marker}\\nspoof`, user: { login: 'contributor' } },
  { id: 2, body: '<!-- infra-copilot-plan:other -->', user: { login: 'github-actions[bot]' } },
  { id: 3, body: null, user: { login: 'github-actions[bot]' } }
];
let calls = [];
const github = {
  rest: { pulls: { get: async args => {
    assert.equal(args.pull_number, 107);
    return { data: { head: { sha: 'current-head' } } };
  } }, issues: {
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
    assert.ok(args.body.includes('current-head'));
  }
  context.payload.pull_request.head.sha = 'old-head';
  await post();
  assert.equal(calls.length, 2, 'outdated plan must not replace the current comment');
})().catch(error => { console.error(error); process.exitCode = 1; });
'''.replace('LEAF', json.dumps(leaf)).replace('SCRIPT', script)
                result = subprocess.run(['node', '-e', harness], cwd=root,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(os.name == 'posix' and shutil.which('jq'), 'guide verification requires shell and jq')
class HcpSnapshotTests(unittest.TestCase):
    def test_compare_lineage_from_raw_state_not_api_metadata(self) -> None:
        guide = (REFERENCES / 'docs/object-storage-state.md').read_text()
        script = guide.split('STATE_DOWNLOAD_URL=', 1)[1].split('\n```', 1)[0]
        script = 'STATE_DOWNLOAD_URL=' + script
        for serial, lineage, expected in ((7, 'source-lineage', 0),
                                          (8, 'source-lineage', 1),
                                          (7, 'different-lineage', 1)):
            with self.subTest(serial=serial, lineage=lineage), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                # Real response shape: serial and download URL, no lineage attribute.
                (root / 'hcp-version.json').write_text(json.dumps({'data': {'attributes': {
                    'serial': 7, 'hosted-state-download-url': 'https://example.test/raw-state',
                }}}))
                (root / 'raw.tfstate').write_text(json.dumps({'serial': 7, 'lineage': 'source-lineage'}))
                (root / 'leaf.tfstate').write_text(json.dumps({'serial': serial, 'lineage': lineage}))
                result = subprocess.run(
                    ['bash', '-eu', '-o', 'pipefail', '-c',
                     'curl() { test "$4" = "https://example.test/raw-state" || return 1; '
                     'cat "$CUTOVER_DIR/raw.tfstate"; }\n' + script],
                    env={**os.environ, 'CUTOVER_DIR': str(root)},
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, expected, result.stderr)


if __name__ == '__main__':
    unittest.main()
