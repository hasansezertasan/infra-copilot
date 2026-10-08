// Copy alongside the workflows to .github/scripts/terraform-destroy.cjs.
const fs = require('node:fs');
const { execFileSync } = require('node:child_process');
const JSON_LIMIT = 128 * 1024 * 1024;

function destructiveChanges(plan) {
  if (!plan || !/^1\./.test(plan.format_version ?? '') ||
      (plan.resource_changes !== undefined && !Array.isArray(plan.resource_changes))) {
    throw new Error('Invalid or unsupported Terraform plan JSON; refusing to proceed.');
  }
  for (const resource of plan.resource_changes ?? []) {
    if (typeof resource?.address !== 'string' || !Array.isArray(resource.change?.actions) ||
        !resource.change.actions.length || !resource.change.actions.every(action =>
          ['no-op', 'create', 'read', 'update', 'delete', 'forget'].includes(action))) {
      throw new Error('Invalid Terraform resource change; refusing to proceed.');
    }
  }
  return (plan.resource_changes ?? [])
    .filter(resource => resource.change.actions.includes('delete'))
    .map(resource => ({ address: resource.address, actions: resource.change.actions }));
}

function codeSpan(value) {
  const longest = (value.match(/`+/g) ?? []).reduce((length, run) => Math.max(length, run.length), 0);
  const delimiter = '`'.repeat(longest + 1);
  return `${delimiter} ${value} ${delimiter}`;
}

function warning(changes, maxLength = Infinity, run = '') {
  if (!changes.length) return '';
  const heading = `### Deletes / replacements (${changes.length})\n\n`;
  const footer = '\nApply requires `allow-destroy` on the producing merged PR. The label records intent, not authorization.\n\n';
  const omitted = `\n…list truncated; [complete inventory in the run summary](${run}).\n`;
  let listing = '';
  for (const change of changes) {
    const line = `- ${codeSpan(change.address)}: ${change.actions.includes('create') ? 'replace' : 'delete'}\n`;
    if (heading.length + listing.length + line.length + footer.length + omitted.length > maxLength) {
      return heading + listing + omitted + footer;
    }
    listing += line;
  }
  return heading + listing + footer;
}

function summaryWarning(changes) {
  const notice = warning(changes);
  if (Buffer.byteLength(notice, 'utf8') > 900000) {
    throw new Error('Destructive inventory exceeds the summary limit; split the change into smaller PRs.');
  }
  return notice;
}

function commentBody({ marker, leaf, head, sha, run, plan, changes, failed }) {
  const notice = warning(changes, 12000, run);
  const frame = text => `${marker}\n${notice}### Terraform Plan: \`${leaf}\`${failed ? ' — **failed**' : ''}\n\nPR head: \`${head}\`\nPlanned commit: \`${sha}\` · [run](${run})\n\n<details>\n<summary>Show Plan</summary>\n\n\`\`\`\`\n${text}\n\`\`\`\`\n</details>`;
  const prefix = '…(truncated, see run logs for the full plan)\n';
  const budget = 65000 - frame('').length;
  if (plan.length > budget) plan = prefix + plan.slice(-(budget - prefix.length));
  return frame(plan);
}

function readPlan(leaf, execute = execFileSync) {
  try {
    // JSON can contain secrets. Explicit pipes prevent execFileSync forwarding
    // stderr; sanitized errors prevent captured output/parse excerpts being logged.
    return JSON.parse(execute('terraform', ['show', '-json', 'tfplan'], {
      cwd: `terraform/${leaf}`, maxBuffer: JSON_LIMIT, stdio: ['pipe', 'pipe', 'pipe'],
    }));
  } catch {
    throw new Error('Cannot read saved Terraform plan JSON (128 MiB limit); refusing apply.');
  }
}

async function enforce({ github, context, core, leaf, loadPlan = readPlan }) {
  const changes = destructiveChanges(loadPlan(leaf));
  if (!changes.length) return;
  await core.summary.addRaw(summaryWarning(changes)).write();
  const { owner, repo } = context.repo;
  const pulls = await github.paginate(github.rest.repos.listPullRequestsAssociatedWithCommit, {
    owner, repo, commit_sha: context.sha,
  });
  const allowed = pulls.some(pr => pr.merged_at && pr.merge_commit_sha === context.sha &&
    pr.base.ref === 'main' && pr.base.repo.full_name.toLowerCase() === `${owner}/${repo}`.toLowerCase() &&
    pr.labels.some(label => label.name === 'allow-destroy'));
  if (!allowed) throw new Error('Refusing deletes/replacements: the merged PR producing this commit must carry allow-destroy. Direct pushes cannot opt in.');
  core.info('Destructive apply explicitly opted into by the producing merged PR.');
}

module.exports = { destructiveChanges, warning, summaryWarning, commentBody, readPlan, enforce };

if (require.main === module) {
  try {
    const input = fs.readFileSync(0);
    if (input.length > JSON_LIMIT) throw new Error('Plan exceeds supported size');
    process.stdout.write(JSON.stringify(destructiveChanges(JSON.parse(input.toString('utf8')))));
  } catch {
    process.stderr.write('Cannot inspect Terraform plan JSON (128 MiB limit).\n');
    process.exitCode = 1;
  }
}
