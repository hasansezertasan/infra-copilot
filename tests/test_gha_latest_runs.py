"""Behavioural tests for the shipped gha-latest-runs helper.

The helper is object-storage mode's answer to HCP's per-workspace run status: it
reads the latest plan run on the current branch and the latest apply run on main,
and has to keep passed, failed, in flight, never run, and unreadable apart. These
run the *shipped* script with `gh` and `git` stubbed on PATH.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills/infra-copilot/references/checks/gha-latest-runs.sh"
SOURCE = REPO_ROOT / ".ai-rulez/skills/infra-copilot/references/checks/gha-latest-runs.sh"
STATUS_RUNBOOK = REPO_ROOT / ".ai-rulez/skills/infra-copilot/references/status.md"


def run(
    run_id: int,
    status: str = "completed",
    conclusion: str = "success",
    event: str = "pull_request",
) -> dict[str, object]:
    return {
        "databaseId": run_id,
        "status": status,
        "conclusion": "" if status != "completed" else conclusion,
        "headSha": "3f9c2a1d0e",
        "event": event,
        "url": f"https://github.com/acme/infra/actions/runs/{run_id}",
    }


def job(name: str, status: str = "completed", conclusion: str = "success") -> dict[str, str]:
    return {"name": name, "status": status, "conclusion": "" if status != "completed" else conclusion}


# Same reason as test_status_check_context: a POSIX shell script, and MSYS path
# rewriting under Git Bash is not what these cases exercise.
@unittest.skipUnless(os.name == "posix", "the helper is a POSIX shell script")
class GhaLatestRunsTests(unittest.TestCase):
    def run_helper(
        self,
        *,
        plan: list[dict[str, object]] | None = None,
        apply: list[dict[str, object]] | None = None,
        jobs: dict[int, list[dict[str, str]]] | None = None,
        branch: str = "feature/dns",
        workflows: tuple[str, ...] = ("terraform-plan.yml", "terraform-apply.yml"),
        gh_exit: int = 0,
        list_fail: dict[str, tuple[int, str]] | None = None,
        jobs_fail: tuple[int, ...] = (),
        backend: str | None = "object-storage",
        repo: str = "acme/infra",
        head: str = "3f9c2a1d0e",
        subdir: str = "",
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            data = root / "data"
            work = root / "work"
            for path in (bin_dir, data, work / ".github/workflows"):
                path.mkdir(parents=True)
            for name in workflows:
                (work / ".github/workflows" / name).write_text("", encoding="utf-8")
            (data / "terraform-plan.yml.json").write_text(json.dumps(plan or []), encoding="utf-8")
            (data / "terraform-apply.yml.json").write_text(json.dumps(apply or []), encoding="utf-8")
            for workflow, (code, message) in (list_fail or {}).items():
                (data / f"{workflow}.fail").write_text(f"{code}\n{message}\n", encoding="utf-8")
            for run_id in jobs_fail:
                (data / f"jobs-{run_id}.fail").write_text("", encoding="utf-8")
            for run_id, entries in (jobs or {}).items():
                (data / f"jobs-{run_id}.json").write_text(
                    json.dumps({"jobs": entries}), encoding="utf-8"
                )
            # The stub evaluates the script's own --jq with the real jq, so a filter
            # that is wrong for gh's JSON fails here rather than in a consuming repo.
            stub = f"""#!/bin/sh
[ {gh_exit} -eq 0 ] || exit {gh_exit}
echo "$*" >> "{data}/calls"
sub="$1 $2"; shift 2
workflow=""; branch=""; filter=""; id=""; all=0
while [ $# -gt 0 ]; do
    case "$1" in
        --workflow) workflow="$2"; shift ;;
        --branch) branch="$2"; shift ;;
        --jq) filter="$2"; shift ;;
        --repo|--json|--limit) shift ;;
        --all) all=1 ;;
        -*) : ;;
        *) id="$1" ;;
    esac
    shift
done
case "$sub" in
    "run list")
        [ "$workflow" = terraform-apply.yml ] && [ "$branch" != main ] && {{ echo "STUB: apply read off main" >&2; exit 99; }}
        # Without --all, gh cannot resolve a disabled workflow and hides its runs.
        [ "$all" = 1 ] || {{ echo "STUB: run list without --all" >&2; exit 99; }}
        if [ -f "{data}/$workflow.fail" ]; then
            sed -n 2p "{data}/$workflow.fail" >&2; exit "$(sed -n 1p "{data}/$workflow.fail")"
        fi
        jq -r "$filter" "{data}/$workflow.json" ;;
    "run view")
        [ -f "{data}/jobs-$id.fail" ] && {{ echo "HTTP 502" >&2; exit 1; }}
        [ -f "{data}/jobs-$id.json" ] || {{ echo "STUB: no jobs for $id" >&2; exit 99; }}
        jq -r "$filter" "{data}/jobs-$id.json" ;;
    *) echo "STUB: unexpected gh $sub" >&2; exit 99 ;;
esac
"""
            (bin_dir / "gh").write_text(stub, encoding="utf-8")
            # The helper always passes --no-optional-locks first; the rest picks the read.
            git_stub = f"""#!/bin/sh
[ "$1" = --no-optional-locks ] || {{ echo "STUB: git without --no-optional-locks" >&2; exit 99; }}
shift
case "$*" in
    "rev-parse --show-toplevel") echo "{work}" ;;
    "rev-parse HEAD") echo "{head}" ;;
    "branch --show-current") echo "{branch}" ;;
    *) echo "STUB: unexpected git $*" >&2; exit 99 ;;
esac
"""
            (bin_dir / "git").write_text(git_stub, encoding="utf-8")
            for name in ("gh", "git"):
                (bin_dir / name).chmod(0o755)
            env = {
                **os.environ,
                "REPO": repo,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
            }
            env.pop("BACKEND", None)
            if backend is not None:
                env["BACKEND"] = backend
            cwd = work / subdir
            cwd.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                ["sh", str(SCRIPT)], cwd=cwd, env=env, capture_output=True, text=True
            )
            calls = data / "calls"
            self.gh_calls = calls.read_text(encoding="utf-8") if calls.exists() else ""
            return result

    def lines(self, result: subprocess.CompletedProcess[str]) -> tuple[str, str]:
        plan, apply = result.stdout.splitlines()
        return plan, apply

    def test_passed_plan_and_apply(self) -> None:
        result = self.run_helper(
            plan=[run(812)],
            apply=[run(809, event="push")],
            jobs={
                812: [job("changes"), job("plan-cloudflare"), job("plan-github", conclusion="skipped"), job("plan")],
                809: [job("apply-cloudflare")],
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        plan, apply = self.lines(result)
        self.assertIn("terraform-plan.yml @ feature/dns  ✓ passed", plan)
        self.assertIn("plan-cloudflare ✓ passed", plan)
        self.assertIn("plan-github – skipped", plan)
        # Only leaf jobs: the `changes` filter and the aggregate `plan` gate are noise.
        self.assertNotIn("changes", plan)
        self.assertNotIn(" plan ✓", plan)
        self.assertIn("terraform-apply.yml @ main  ✓ passed", apply)
        self.assertIn("run 809 (push, 3f9c2a1)", apply)

    def test_failed_apply_on_main_exits_1(self) -> None:
        result = self.run_helper(
            plan=[run(812)],
            apply=[run(809, conclusion="failure", event="push")],
            jobs={812: [job("plan-cloudflare")], 809: [job("apply-cloudflare", conclusion="failure")]},
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        _, apply = self.lines(result)
        self.assertIn("✗ failed (failure)", apply)
        self.assertIn("apply-cloudflare ✗ failed (failure)", apply)
        self.assertIn("actions/runs/809", apply)

    def test_in_progress_run_keeps_its_fields_aligned(self) -> None:
        """An in-flight run has an empty conclusion; a tab delimiter collapsed it."""
        result = self.run_helper(
            plan=[run(812, status="in_progress")],
            jobs={812: [job("plan-cloudflare", status="queued")]},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        plan, apply = self.lines(result)
        self.assertIn("⏳ in progress (in_progress)", plan)
        self.assertIn("run 812 (pull_request, 3f9c2a1)", plan)
        self.assertIn("plan-cloudflare ⏳ in progress (queued)", plan)
        self.assertIn("no runs yet", apply)

    def test_no_runs_yet_is_not_a_failure(self) -> None:
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        plan, apply = self.lines(result)
        self.assertIn("terraform-plan.yml @ feature/dns  – no runs yet", plan)
        self.assertIn("terraform-apply.yml @ main  – no runs yet", apply)

    def test_cancelled_run_is_unknown_not_failed(self) -> None:
        result = self.run_helper(plan=[run(812, conclusion="cancelled")], jobs={812: []})
        self.assertEqual(result.returncode, 0, result.stderr)
        plan, _ = self.lines(result)
        self.assertIn("? cancelled", plan)

    def test_missing_workflow_file_is_not_installed(self) -> None:
        result = self.run_helper(workflows=("terraform-plan.yml",))
        self.assertEqual(result.returncode, 0, result.stderr)
        _, apply = self.lines(result)
        self.assertIn("not installed", apply)
        self.assertNotIn("terraform-apply.yml", self.gh_calls)

    def test_detached_head_skips_the_plan_read(self) -> None:
        result = self.run_helper(branch="")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan, _ = self.lines(result)
        self.assertIn("detached HEAD", plan)
        self.assertNotIn("terraform-plan.yml", self.gh_calls)

    def test_unauthenticated_gh_cannot_verify(self) -> None:
        result = self.run_helper(gh_exit=4)
        self.assertEqual(result.returncode, 2)
        plan, apply = self.lines(result)
        for line in (plan, apply):
            self.assertIn("? could not verify", line)
            self.assertIn("gh auth login", line)

    def test_api_failure_cannot_verify(self) -> None:
        result = self.run_helper(gh_exit=1)
        self.assertEqual(result.returncode, 2)
        plan, _ = self.lines(result)
        self.assertIn("? could not verify: could not list terraform-plan.yml", plan)

    def test_failed_apply_read_keeps_the_plan_line(self) -> None:
        """One unreadable workflow must not discard the other line's real result."""
        result = self.run_helper(
            plan=[run(812, conclusion="failure")],
            jobs={812: [job("plan-cloudflare", conclusion="failure")]},
            list_fail={"terraform-apply.yml": (1, "HTTP 502")},
        )
        # A failure that was read wins over the line that could not be.
        self.assertEqual(result.returncode, 1, result.stderr)
        plan, apply = self.lines(result)
        self.assertIn("✗ failed (failure)", plan)
        self.assertIn("? could not verify", apply)

    def test_failed_plan_read_still_reads_apply(self) -> None:
        result = self.run_helper(
            apply=[run(809, event="push")],
            jobs={809: [job("apply-cloudflare")]},
            list_fail={"terraform-plan.yml": (1, "HTTP 502")},
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        plan, apply = self.lines(result)
        self.assertIn("? could not verify", plan)
        self.assertIn("✓ passed", apply)

    def test_unreadable_jobs_mark_only_that_line(self) -> None:
        result = self.run_helper(
            plan=[run(812)],
            apply=[run(809, event="push")],
            jobs={809: [job("apply-cloudflare")]},
            jobs_fail=(812,),
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        plan, apply = self.lines(result)
        self.assertIn("✓ passed  run 812", plan)
        self.assertIn("? jobs unreadable", plan)
        self.assertIn("apply-cloudflare ✓ passed", apply)

    def test_workflow_unknown_to_github_is_no_runs_yet(self) -> None:
        """Committed on a branch, never run: gh cannot resolve --workflow at all."""
        result = self.run_helper(
            list_fail={
                "terraform-plan.yml": (1, "could not find any workflows named terraform-plan.yml"),
                "terraform-apply.yml": (1, "could not find any workflows named terraform-apply.yml"),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        plan, apply = self.lines(result)
        self.assertIn("– no runs yet (GitHub has not registered terraform-plan.yml yet)", plan)
        self.assertIn("– no runs yet", apply)

    def test_failed_non_leaf_job_is_named(self) -> None:
        """A `validate` failure fails the run; listing only leaf jobs showed all green."""
        result = self.run_helper(
            plan=[run(812, conclusion="failure")],
            jobs={
                812: [
                    job("plan-cloudflare"),
                    job("validate (cloudflare)", conclusion="failure"),
                    job("validate (github)"),
                ]
            },
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        plan, _ = self.lines(result)
        self.assertIn("validate (cloudflare) ✗ failed (failure)", plan)
        self.assertNotIn("validate (github)", plan)

    def test_plan_for_an_older_commit_says_so(self) -> None:
        result = self.run_helper(plan=[run(812)], jobs={812: []}, head="9e8d7c6b5a")
        plan, _ = self.lines(result)
        self.assertIn("(pull_request, 3f9c2a1, not HEAD 9e8d7c6)", plan)

    def test_runs_from_a_subdirectory(self) -> None:
        result = self.run_helper(subdir="terraform/cloudflare")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("not installed", result.stdout)

    def test_missing_repo_cannot_verify(self) -> None:
        result = self.run_helper(repo="")
        self.assertEqual(result.returncode, 2)
        self.assertIn("REPO is not set", result.stderr)

    def test_unset_backend_is_hcp(self) -> None:
        """references/config.md: a missing backend is hcp, not object-storage."""
        result = self.run_helper(backend=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not applicable: backend is hcp (default)", result.stdout)
        self.assertEqual(self.gh_calls, "")

    def test_hcp_backend_is_not_applicable(self) -> None:
        result = self.run_helper(backend="hcp")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not applicable", result.stdout)
        self.assertEqual(self.gh_calls, "")


class GhaLatestRunsWiringTests(unittest.TestCase):
    def test_shipped_copy_matches_source(self) -> None:
        self.assertEqual(SCRIPT.read_bytes(), SOURCE.read_bytes())

    def test_status_runbook_links_the_helper(self) -> None:
        runbook = STATUS_RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("(checks/gha-latest-runs.sh)", runbook)
        # The link alone told the agent to execute a path; give it the invocation.
        self.assertIn('`sh "$INFRA_COPILOT_REFERENCES/checks/gha-latest-runs.sh"`', runbook)

    @unittest.skipUnless(os.name == "posix", "the executable bit is a POSIX mode")
    def test_both_copies_are_executable(self) -> None:
        """Committed 100644, a direct execution failed with Permission denied."""
        for path in (SOURCE, SCRIPT):
            self.assertTrue(os.access(path, os.X_OK), f"{path} is not executable")


if __name__ == "__main__":
    unittest.main()
