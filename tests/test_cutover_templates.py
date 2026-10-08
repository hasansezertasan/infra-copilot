"""Execute source workflow scripts with mocked Terraform and GitHub APIs."""
from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / ".ai-rulez/skills/infra-copilot/references/templates"
LEAVES = ("cloudflare", "github")


def read_template(operation: str) -> str:
    return (TEMPLATES / f"terraform-{operation}.yml").read_text(encoding="utf-8")


def extract_job(workflow: str, job_name: str) -> str:
    matched = re.search(rf"^  {re.escape(job_name)}:\n(.*?)(?=^  [\w-]+:\n|\Z)", workflow, re.M | re.S)
    if matched is None:
        raise AssertionError(f"Missing job: {job_name}")
    return matched[1]


def extract_script(job_text: str, step_name: str, field: str = "run") -> str:
    step_text = job_text.split(f"      - name: {step_name}\n", 1)[1].split("\n      - ", 1)[0]
    matched = re.search(rf"^( +){field}: \|\n((?:\1  .*\n|\n)+)", step_text + "\n", re.M)
    if matched is None:
        raise AssertionError(f"Missing literal script: {step_name}")
    return textwrap.dedent(matched[2])


class CutoverTemplateTests(unittest.TestCase):
    def test_checkout_credentials_and_apply_ordering(self) -> None:
        for operation in ("plan", "apply"):
            workflow = read_template(operation)
            checkouts = re.findall(r"      - uses: actions/checkout@[^\n]+\n((?:        .*\n)+)", workflow)
            self.assertEqual(len(checkouts), workflow.count("uses: actions/checkout@"))
            self.assertGreater(len(checkouts), 0)
            for checkout in checkouts:
                self.assertIn("persist-credentials: false", checkout)
        for leaf_name in LEAVES:
            job_text = extract_job(read_template("apply"), f"apply-{leaf_name}")
            self.assertLess(job_text.index("name: Terraform Init"), job_text.index("name: Refuse empty state"))
            self.assertLess(job_text.index("name: Refuse empty state"), job_text.index("name: Terraform Apply"))
            self.assertEqual(job_text.count("timeout-minutes: 120"), 1)
            self.assertIn(f"ALLOW_EMPTY_STATE: ${{{{ vars.TF_ALLOW_EMPTY_STATE_{leaf_name.upper()} }}}}", job_text)

    @unittest.skipUnless(os.name == "posix", "workflow scripts require POSIX shell")
    def test_reviewed_state_guard_requires_state_unless_first_creation_is_authorized(self) -> None:
        scenarios = [
            (1, "", "false", False),
            (1, "resource.example", "false", False),
            (1, "", "true", True),
            (1, "partial.output", "true", True),
            (0, "", "false", False),
            (0, "", "true", True),
            (0, "", "TRUE", False),
            (0, "", "", False),
            (0, "resource.example\n", "false", True),
        ]
        with tempfile.TemporaryDirectory(prefix="cutover guard ") as directory:
            root_path = Path(directory)
            terraform = root_path / "terraform"
            terraform.write_text(
                '#!/bin/sh\n[ "$*" = "state list" ] || exit 99\n'
                'printf "%s" "$STATE_CONTENT"\nexit "$STATE_STATUS"\n', encoding="utf-8")
            terraform.chmod(0o755)
            for leaf_name, scenario in itertools.product(LEAVES, scenarios):
                state_status, state_content, allow_empty, expected = scenario
                with self.subTest(leaf=leaf_name, scenario=scenario):
                    guard_script = extract_script(
                        extract_job(read_template("apply"), f"apply-{leaf_name}"), "Refuse empty state")
                    result = subprocess.run(
                        ["bash", "-eu", "-o", "pipefail", "-c", guard_script], text=True, capture_output=True,
                        env=os.environ | {"PATH": f"{root_path}{os.pathsep}{os.environ['PATH']}",
                                          "STATE_STATUS": str(state_status), "STATE_CONTENT": state_content,
                                          "ALLOW_EMPTY_STATE": allow_empty},
                    )
                    self.assertEqual(result.returncode == 0, expected, result.stdout + result.stderr)
                    if state_status and allow_empty != "true":
                        self.assertIn("cannot read state", result.stdout)

    def test_reviewed_plan_concurrency_is_preserved(self) -> None:
        workflow = read_template("plan")
        self.assertIn("group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}", workflow)
        self.assertIn("cancel-in-progress: true", workflow)

    @unittest.skipUnless(os.name == "posix", "workflow scripts require POSIX shell")
    def test_mixed_backend_routing_executes_only_changed_object_storage_leaves(self) -> None:
        for operation in ("plan", "apply"):
            workflow = read_template(operation)
            changes_job = extract_job(workflow, "changes")
            route_script = extract_script(changes_job, "Route object-storage leaves")
            for leaf_name in LEAVES:
                self.assertIn(f"{leaf_name.upper()}_BACKEND: object-storage", workflow)
                self.assertIn(f"{leaf_name}: ${{{{ steps.route.outputs.{leaf_name} }}}}", changes_job)
                job_text = extract_job(workflow, f"{operation}-{leaf_name}")
                self.assertIn(f"if: needs.changes.outputs.{leaf_name} == 'true'", job_text)
                if operation == "plan":
                    self.assertIn("&& (github.event_name != 'pull_request' || "
                                  "github.event.pull_request.head.repo.full_name == github.repository)", job_text)
            with tempfile.TemporaryDirectory() as directory:
                output_path = Path(directory) / "outputs"
                for backends in itertools.product(("object-storage", "hcp"), repeat=2):
                    for changed in itertools.product(("false", "true"), repeat=2):
                        with self.subTest(operation=operation, backends=backends, changed=changed):
                            output_path.write_text("", encoding="utf-8")
                            environment = os.environ | {"GITHUB_OUTPUT": str(output_path)}
                            for leaf_name, backend, change in zip(LEAVES, backends, changed):
                                environment[f"{leaf_name.upper()}_BACKEND"] = backend
                                environment[f"{leaf_name.upper()}_CHANGED"] = "true" if operation == "apply" else change
                            result = subprocess.run(["bash", "-eu", "-c", route_script], env=environment,
                                                    text=True, capture_output=True)
                            self.assertEqual(result.returncode, 0, result.stderr)
                            outputs = dict(line.split("=", 1) for line in output_path.read_text().splitlines())
                            for leaf_name, backend, change in zip(LEAVES, backends, changed):
                                self.assertEqual(outputs[leaf_name],
                                                  str(backend == "object-storage" and (operation == "apply" or change == "true")).lower())

    @unittest.skipUnless(os.name == "posix" and shutil.which("jq"), "aggregate script requires POSIX shell and jq")
    def test_aggregate_accepts_hcp_only_changes_but_requires_object_storage_plans(self) -> None:
        aggregate_job = extract_job(read_template("plan"), "plan")
        for leaf_name in LEAVES:
            self.assertIn(f"${{{{ needs.changes.outputs.{leaf_name} }}}}", aggregate_job)
        scenarios = [
            ("false", "false", "skipped", "skipped", "success", True),
            ("true", "false", "success", "skipped", "success", True),
            ("false", "true", "skipped", "success", "success", True),
            ("true", "false", "skipped", "skipped", "success", False),
            ("false", "true", "skipped", "failure", "success", False),
            ("false", "false", "skipped", "skipped", "failure", False),
            ("true", "false", "cancelled", "skipped", "success", False),
        ]
        for cloudflare, github, cf_result, gh_result, validation, expected in scenarios:
            with self.subTest(scenario=(cloudflare, github, cf_result, gh_result, validation)):
                prerequisites = {"changes": {"result": "success"}, "plan-cloudflare": {"result": cf_result},
                                 "plan-github": {"result": gh_result}, "validate": {"result": validation}}
                aggregate_script = extract_script(aggregate_job, "Evaluate prerequisite job statuses")
                aggregate_script = aggregate_script.replace("${{ toJson(needs) }}", json.dumps(prerequisites))
                result = subprocess.run(["bash", "-eu", "-c", aggregate_script], text=True, capture_output=True,
                                        env=os.environ | {"CLOUDFLARE_CHANGED": cloudflare, "GITHUB_CHANGED": github})
                self.assertEqual(result.returncode == 0, expected, result.stdout + result.stderr)

    def test_apply_has_no_path_filters_and_converges_all_active_backends(self) -> None:
        workflow = read_template("apply")
        trigger = workflow.split("concurrency:", 1)[0]
        self.assertNotIn('paths:', trigger)
        self.assertIn('workflow_dispatch:', trigger)
        changes_job = extract_job(workflow, "changes")
        self.assertNotIn('paths-filter', changes_job)
        for leaf_name in LEAVES:
            self.assertIn(f"{leaf_name.upper()}_CHANGED: 'true'", changes_job)

    @unittest.skipUnless(shutil.which("node"), "comment script requires Node.js")
    def test_comments_paginate_match_only_owned_leaf_marker_and_await_writes(self) -> None:
        harness = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const marker = `<!-- infra-copilot-plan:${input.leaf} -->`;
const bot = {login: 'github-actions[bot]', type: 'Bot'};
const impostors = [
  {id: 1, body: marker, user: {login: 'contributor', type: 'User'}},
  {id: 2, body: marker, user: {login: 'other[bot]', type: 'Bot'}},
  {id: 4, body: '<!-- infra-copilot-plan:other -->', user: bot},
  {id: 5, body: null, user: bot},
  {id: 6, body: marker, user: null}
];
const pages = [impostors, input.existing ? [{id: 107, body: marker + '\nold plan', user: bot}] : []];
let paginated = false;
let completed = false;
let mutation;
const issues = {
  listComments: async ({page}) => pages[page - 1] || [],
  updateComment: async params => {
    await new Promise(resolve => setTimeout(resolve, 10));
    mutation = {kind: 'update', ...params}; completed = true;
  },
  createComment: async params => {
    await new Promise(resolve => setTimeout(resolve, 10));
    mutation = {kind: 'create', ...params}; completed = true;
  }
};
const github = {rest: {issues, pulls: {get: async params => {
  if (params.pull_number !== 107) throw new Error('wrong pull request');
  return {data: {head: {sha: 'current-head'}}};
}}}, paginate: async (method, params) => {
  if (method !== issues.listComments || params.per_page !== 100 || params.issue_number !== 107)
    throw new Error('wrong pagination request');
  paginated = true;
  const comments = [];
  for (let page = 1; ; page++) {
    const batch = await method({...params, page});
    if (!batch.length) break;
    comments.push(...batch);
  }
  return comments;
}};
const mockedRequire = name => {
  if (name === './.github/scripts/terraform-destroy.cjs') return require(input.helperPath);
  if (name !== 'fs') throw new Error('unexpected module');
  return {existsSync: path => path === `terraform/${input.leaf}/plan.txt`, readFileSync: (path, encoding) => {
    if (path === `terraform/${input.leaf}/destroys.json` && encoding === 'utf8') return '[]';
    if (path !== `terraform/${input.leaf}/plan.txt` || encoding !== 'utf8')
      throw new Error('wrong plan file');
    return input.plan;
  }};
};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
(async () => {
  const context = {repo: {owner: 'owner', repo: 'repo'}, issue: {number: 107},
    serverUrl: 'https://github.com', runId: 123,
    sha: 'planned-merge', payload: {pull_request: {head: {sha: 'current-head'}}}};
  process.env.EXITCODE = '0'; process.env.PLAN_OUTCOME = 'success'; process.env.INVENTORY_OUTCOME = 'success';
  const post = new AsyncFunction('require', 'github', 'context', 'core', input.script);
  await post(mockedRequire, github, context, {notice: () => {}});
  if (!paginated || !completed) throw new Error('pagination or awaited mutation missing');
  context.payload.pull_request.head.sha = 'old-head';
  paginated = false;
  completed = false;
  let noticed = false;
  await post(mockedRequire, github, context, {notice: () => {noticed = true;}});
  if (!noticed || paginated || completed) throw new Error('outdated head must not post');
  process.stdout.write(JSON.stringify(mutation));
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
        for leaf_name, existing, plan_text in itertools.product(LEAVES, (False, True), ("short plan", "x" * 100000)):
            with self.subTest(leaf=leaf_name, existing=existing, length=len(plan_text)):
                comment_script = extract_script(
                    extract_job(read_template("plan"), f"plan-{leaf_name}"), "Post Plan to PR", "script")
                result = subprocess.run(
                    ["node", "-e", harness], text=True, capture_output=True,
                    input=json.dumps({"leaf": leaf_name, "existing": existing, "plan": plan_text,
                                      "script": comment_script, "helperPath": str(TEMPLATES / 'terraform-destroy.cjs')}),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                mutation = json.loads(result.stdout)
                self.assertEqual(mutation["kind"], "update" if existing else "create")
                self.assertEqual(mutation["owner"], "owner")
                self.assertEqual(mutation["repo"], "repo")
                self.assertEqual(mutation["comment_id" if existing else "issue_number"], 107)
                self.assertTrue(mutation["body"].startswith(f"<!-- infra-copilot-plan:{leaf_name} -->"))
                self.assertIn("PR head: `current-head`", mutation["body"])
                self.assertIn("Planned commit: `planned-merge`", mutation["body"])
                self.assertLess(len(mutation["body"]), 65536)
                if len(plan_text) > 65535:
                    self.assertIn("truncated", mutation["body"])
                else:
                    self.assertIn(plan_text, mutation["body"])


if __name__ == "__main__":
    unittest.main()
