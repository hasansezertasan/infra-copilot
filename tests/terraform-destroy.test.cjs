const assert = require('node:assert/strict');
const { test } = require('node:test');
const { spawnSync } = require('node:child_process');
const modulePath = require.resolve('../.ai-rulez/skills/infra-copilot/references/templates/terraform-destroy.cjs');
const { destructiveChanges, warning, summaryWarning, commentBody, readPlan, enforce } = require(modulePath);

const resource = (address, actions) => ({ address, change: { actions, before: { secret: 'sensitive-sentinel' } } });
const safe = { format_version: '1.2', resource_changes: ['no-op', 'create', 'read', 'update', 'forget'].map(action => resource(action, [action])) };
const plan = { format_version: '1.2', resource_changes: [resource('example.deleted', ['delete']),
  resource('example.replaced', ['delete', 'create']), resource('example.create_first', ['create', 'delete'])] };
const context = { repo: { owner: 'owner', repo: 'repo' }, sha: 'current-sha' };
const merged = (overrides = {}) => ({ merged_at: '2026-10-08', merge_commit_sha: context.sha,
  base: { ref: 'main', repo: { full_name: 'owner/repo' } }, labels: [{ name: 'allow-destroy' }], ...overrides });

function harness(pulls, input = plan) {
  const calls = [];
  const github = { rest: { repos: { listPullRequestsAssociatedWithCommit: 'endpoint' } },
    paginate: async (...args) => { calls.push(args); if (pulls instanceof Error) throw pulls; return pulls; } };
  const core = { info() {}, summary: { addRaw() { return this; }, async write() {} } };
  return { args: { github, context, core, leaf: 'example', loadPlan: () => input }, calls };
}

test('delete and both replacement orders are destructive; forget and safe operations are allowed', () => {
  assert.deepEqual(destructiveChanges(safe), []);
  assert.deepEqual(destructiveChanges({ format_version: '1.2' }), []);
  assert.equal(destructiveChanges(plan).length, 3);
  assert.match(warning(destructiveChanges(plan)), /example.deleted `: delete/);
  assert.match(warning(destructiveChanges(plan)), /example.create_first `: replace/);
});

test('CLI publishes only addresses/actions and sanitizes invalid input errors', () => {
  const output = spawnSync(process.execPath, [modulePath], { input: JSON.stringify(plan), encoding: 'utf8' });
  assert.equal(output.status, 0);
  assert.deepEqual(JSON.parse(output.stdout), destructiveChanges(plan));
  assert.ok(!output.stdout.includes('sensitive-sentinel'));
  const failure = spawnSync(process.execPath, [modulePath], { input: 'sensitive-sentinel', encoding: 'utf8' });
  assert.notEqual(failure.status, 0);
  assert.ok(!failure.stderr.includes('sensitive-sentinel'));
});

test('safe plans never need a PR lookup; a producing labeled PR permits destruction', async () => {
  const safeRun = harness(new Error('API unavailable'), safe);
  await enforce(safeRun.args);
  assert.equal(safeRun.calls.length, 0);
  const optedIn = harness([merged()]);
  await enforce(optedIn.args);
  assert.deepEqual(optedIn.calls[0][1], { owner: 'owner', repo: 'repo', commit_sha: context.sha });
});

for (const [scenario, pulls] of [
  ['unlabeled merged PR', [merged({ labels: [] })]],
  ['direct push', []], ['open PR', [merged({ merged_at: null })]],
  ['older merged PR', [merged({ merge_commit_sha: 'older' })]],
  ['wrong base', [merged({ base: { ref: 'other', repo: { full_name: 'owner/repo' } } })]],
  ['wrong repo', [merged({ base: { ref: 'main', repo: { full_name: 'other/repo' } } })]],
]) test(`refuses destructive apply for ${scenario}`, async () => {
  await assert.rejects(enforce(harness(pulls).args), /Refusing deletes/);
});

test('API failures and malformed plan shapes fail closed', async () => {
  await assert.rejects(enforce(harness(new Error('API unavailable')).args), /API unavailable/);
  for (const invalid of [{}, { format_version: '2.0' }, { format_version: '1.2', resource_changes: null },
    { format_version: '1.2', resource_changes: [null] },
    { format_version: '1.2', resource_changes: [resource('bad', 'update')] },
    { format_version: '1.2', resource_changes: [resource('bad', ['unknown'])] }]) {
    await assert.rejects(enforce(harness([], invalid).args));
  }
});

test('saved reader uses the exact plan and sanitized piped subprocess output', () => {
  let call;
  assert.deepEqual(readPlan('example', (...args) => { call = args; return JSON.stringify(plan); }), plan);
  assert.deepEqual(call, ['terraform', ['show', '-json', 'tfplan'], {
    cwd: 'terraform/example', maxBuffer: 128 * 1024 * 1024, stdio: ['pipe', 'pipe', 'pipe'],
  }]);
  const script = `const { readPlan } = require(${JSON.stringify(modulePath)});
    const { execFileSync } = require('node:child_process');
    try { readPlan('example', (command, args, options) => execFileSync(process.execPath,
      ['-e', 'process.stderr.write("sensitive-sentinel"); process.exit(1)'], { ...options, cwd: process.cwd() })); }
    catch (error) { console.error(error.message); }`;
  const output = spawnSync(process.execPath, ['-e', script], { encoding: 'utf8' });
  assert.equal(output.status, 0);
  assert.match(output.stderr, /refusing apply/);
  assert.ok(!output.stderr.includes('sensitive-sentinel'));
  assert.throws(() => readPlan('example', () => 'sensitive-sentinel'), /refusing apply/);
});

test('comments and UTF-8 summaries respect GitHub limits', () => {
  const changes = Array.from({ length: 10000 }, (_, index) => ({ address: `example.resource["${index}-${'é'.repeat(100)}"]`, actions: ['delete'] }));
  const body = commentBody({ marker: '<!-- infra-copilot-plan:example -->', leaf: 'example', head: 'head',
    sha: 'sha', run: 'https://github.com/owner/repo/actions/runs/1', plan: 'p'.repeat(100000), changes });
  assert.ok(body.length <= 65000);
  assert.ok(body.indexOf('Deletes / replacements (10000)') < body.indexOf('<details>'));
  assert.match(body, /list truncated.*complete inventory/);
  assert.throws(() => summaryWarning(changes), /split the change/);
});

test('Markdown code spans support backticks and unusually long resource keys', () => {
  assert.match(warning([{ address: 'resource["key``text"]', actions: ['delete'] }]), /``` resource\["key``text"\] ```/);
  assert.ok(warning([{ address: `resource["${'`x'.repeat(150000)}"]`, actions: ['delete'] }]).includes('`` resource['));
});
