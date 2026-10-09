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


class WorkflowConvergenceTests(unittest.TestCase):
    def test_every_apply_run_includes_every_leaf(self) -> None:
        template = (REFERENCES / 'templates/terraform-apply.yml').read_text()
        triggers = template.split('on:\n', 1)[1].split('\nconcurrency:', 1)[0]
        self.assertIn('branches: [main]', triggers)
        self.assertIn('  workflow_dispatch:', triggers)
        self.assertNotIn('paths:', triggers)
        self.assertNotIn('paths-ignore:', triggers)
        self.assertIn('group: terraform-apply-${{ github.ref }}', template)
        self.assertIn('cancel-in-progress: false', template)
        jobs = template.split('\njobs:\n', 1)[1]
        routes = jobs.split('  changes:\n', 1)[1].split('\n  apply-', 1)[0]
        self.assertNotIn('paths-filter', routes)
        for leaf in ('cloudflare', 'github'):
            job = jobs.split(f'  apply-{leaf}:\n', 1)[1].split('\n  apply-', 1)[0]
            header, steps = job.split('    steps:\n', 1)
            self.assertIn('    needs: changes', header)
            self.assertIn(f"    if: needs.changes.outputs.{leaf} == 'true'", header)
            self.assertIn(f"{leaf.upper()}_CHANGED: 'true'", routes)
            self.assertIn('environment: production', header)
            self.assertLess(steps.index("Refuse to apply a commit that is not main's tip"),
                            steps.index('name: Terraform Apply'))
            self.assertLess(steps.index('name: Terraform Plan'),
                            steps.index('name: Refuse destructive apply without opt-in'))
            self.assertLess(steps.index('name: Refuse destructive apply without opt-in'),
                            steps.index("Refuse to apply a commit that is not main's tip"))

    def test_dispatch_plans_all_leaves_and_prs_keep_filter_and_fork_gate(self) -> None:
        template = (REFERENCES / 'templates/terraform-plan.yml').read_text()
        filter_step = template.split('        id: filter\n', 1)[1].split('        with:', 1)[0]
        self.assertIn("if: github.event_name == 'pull_request'", filter_step)
        for leaf in ('cloudflare', 'github'):
            output = re.search(rf"^          {leaf.upper()}_CHANGED: \$\{{\{{ (.*?) \}}\}}$", template, re.M).group(1)
            job = template.split(f'  plan-{leaf}:\n', 1)[1].split('    steps:', 1)[0]
            condition = re.search(r'    if: (.*)', job).group(1)
            harness = """
const assert = require('node:assert/strict');
for (const [event, changed, sameRepo, expected] of [
  ['workflow_dispatch', undefined, true, true],
  ['pull_request', 'true', true, true],
  ['pull_request', 'false', true, false],
  ['pull_request', 'true', false, false],
]) {
  const github = { event_name: event, repository: 'owner/repo', event: event === 'workflow_dispatch' ? {} : {
    pull_request: { head: { repo: { full_name: sameRepo ? 'owner/repo' : 'fork/repo' } } }
  } };
  const steps = { filter: { outputs: { [LEAF]: changed } } };
  const selected = OUTPUT;
  const needs = { changes: { outputs: { [LEAF]: selected } } };
  assert.equal(CONDITION, expected, event + ':' + changed + ':' + sameRepo);
  if (event === 'workflow_dispatch') assert.equal(selected, 'true');
}
""".replace('LEAF', json.dumps(leaf)).replace('OUTPUT', output).replace('CONDITION', condition)
            result = subprocess.run(['node', '-e', harness], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(os.name == 'posix', 'main-tip guard requires POSIX shell')
class ApplyMainTipTests(unittest.TestCase):
    def test_only_main_tip_can_apply_and_api_errors_fail_closed(self) -> None:
        template = (REFERENCES / 'templates/terraform-apply.yml').read_text()
        scripts = re.findall(r"      - name: Refuse to apply a commit that is not main's tip\n"
                             r".*?        run: \|\n(.*?)(?=\n      - name:)", template, re.S)
        self.assertEqual(len(scripts), 2)
        for script in scripts:
            for ref, sha, tip, status, expected in (
                ('refs/heads/main', 'current', 'current', 0, 0),
                ('refs/heads/main', 'old', 'current', 0, 1),
                ('refs/heads/feature', 'current', 'current', 0, 1),
                ('refs/tags/main', 'current', 'current', 0, 1),
                ('refs/heads/main', 'current', '', 1, 1),
                ('refs/heads/main', 'current', '', 0, 1),
                ('refs/heads/main', 'current', 'current', 1, 1),
            ):
                with self.subTest(ref=ref, sha=sha, tip=tip, status=status):
                    result = subprocess.run(
                        ['bash', '-eu', '-o', 'pipefail', '-c',
                         'gh() { test "$*" = "api repos/owner/repo/commits/main --jq .sha" || return 99; '
                         'printf "%s" "$TEST_TIP"; return "$TEST_STATUS"; }\n'
                         + textwrap.dedent(script)],
                        env={**os.environ, 'GITHUB_REPOSITORY': 'owner/repo',
                             'GITHUB_REF': ref, 'GITHUB_SHA': sha,
                             'TEST_TIP': tip, 'TEST_STATUS': str(status)},
                        capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, expected, result.stderr)


class PlanCommentTests(unittest.TestCase):
    def test_create_then_update_only_owned_leaf_comment(self) -> None:
        template = (REFERENCES / 'templates/terraform-plan.yml').read_text()
        scripts = re.findall(r'      - name: Post Plan to PR\n.*?          script: \|\n(.*?)(?=\n      - name:)', template, re.S)
        self.assertEqual(len(scripts), 2)
        for leaf, script in zip(('cloudflare', 'github'), scripts):
            script = textwrap.dedent(script)
            with self.subTest(leaf=leaf), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = root / 'terraform' / leaf / 'plan.txt'
                plan.parent.mkdir(parents=True)
                plan.write_text('No changes.')
                (plan.parent / 'destroys.json').write_text('[]')
                helper = root / '.github/scripts/terraform-destroy.cjs'
                helper.parent.mkdir(parents=True)
                shutil.copyfile(REFERENCES / 'templates/terraform-destroy.cjs', helper)
                # paginate supplies comments beyond page one; spoofed markers and other
                # leaves must not be selected. Reject dropped await calls too.
                harness = '''
const assert = require('node:assert/strict');
const leaf = LEAF;
const marker = `<!-- infra-copilot-plan:${leaf} -->`;
const context = { repo: { owner: 'owner', repo: 'infra' }, issue: { number: 107 }, sha: 'planned-merge',
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
    assert.ok(args.body.includes('PR head: `current-head`'));
    assert.ok(args.body.includes('Planned commit: `planned-merge`'));
  }
  context.payload.pull_request.head.sha = 'old-head';
  await post();
  assert.equal(calls.length, 2, 'outdated plan must not replace the current comment');
  context.payload.pull_request.head.sha = 'current-head';
  process.env.PLAN_OUTCOME = 'failure';
  require('fs').unlinkSync(`terraform/${leaf}/destroys.json`);
  await post();
  assert.equal(calls.length, 3, 'inspection failure must invalidate the previous success');
  assert.ok(calls[2][1].body.includes('**failed**'));
  assert.ok(calls[2][1].body.includes('Plan or destructive inspection failed'));
  process.env.PLAN_OUTCOME = 'success';
  process.env.INVENTORY_OUTCOME = 'failure';
  await post();
  assert.equal(calls.length, 4, 'summary failure must also invalidate the previous success');
  assert.ok(calls[3][1].body.includes('**failed**'));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''.replace('LEAF', json.dumps(leaf)).replace('SCRIPT', script)
                result = subprocess.run(['node', '-e', harness], cwd=root,
                                        env={**os.environ, 'EXITCODE': '0', 'PLAN_OUTCOME': 'success', 'INVENTORY_OUTCOME': 'success'},
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


class InventorySummaryTests(unittest.TestCase):
    def test_manual_plans_publish_inventory_without_a_pr(self) -> None:
        template = (REFERENCES / 'templates/terraform-plan.yml').read_text()
        blocks = re.findall(r'      - name: Summarize Destructive Changes\n(.*?)(?=\n      - name:)', template, re.S)
        self.assertEqual(len(blocks), 2)
        for leaf, block in zip(('cloudflare', 'github'), blocks):
            self.assertNotIn('pull_request', block)
            script = textwrap.dedent(block.split('          script: |\n', 1)[1])
            with self.subTest(leaf=leaf), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                inventory = root / f'terraform/{leaf}/destroys.json'
                inventory.parent.mkdir(parents=True)
                inventory.write_text(json.dumps([{'address': 'example.deleted', 'actions': ['delete']}]))
                helper = root / '.github/scripts/terraform-destroy.cjs'
                helper.parent.mkdir(parents=True)
                shutil.copyfile(REFERENCES / 'templates/terraform-destroy.cjs', helper)
                harness = '''
const assert = require('node:assert/strict');
let notice = '', written = false;
const core = { summary: {
  addRaw(text) { notice = text; return this; },
  async write() { await new Promise(resolve => setTimeout(resolve, 5)); written = true; }
} };
(async () => {
SCRIPT
assert.ok(written);
assert.ok(notice.includes('example.deleted'));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''.replace('SCRIPT', script)
                result = subprocess.run(['node', '-e', harness], cwd=root, capture_output=True, text=True)
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
