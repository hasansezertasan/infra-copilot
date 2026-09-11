---
type: Guide
title: Project Workflow
---

# Project Workflow

<!-- truth: start -->
- Task files under `.agents/bundles/specs/<flow_id>/tasks/` are authoritative; `spec.md` is the synchronized checklist and continuity view.
- Use the repository's canonical setup, focused-test, lint/type/build, and aggregate verification commands.
- Every task declares and justifies one `verification_strategy`; only observable behavior and defect correction require an initial failing test.
- Record durable findings in the task's `## Notes & Discoveries` and preserve unrelated worktree changes.
- Consumer operational skills install only under `.agents/skills/`. Product, knowledge, research, and specs remain under `.agents/bundles/`.
- Flow never creates, moves, force-updates, or deletes Git tags, and never pushes automatically.
- **Most of the tree is generated.** Edit sources in `.ai-rulez/`, then run `make generate`. Check `.ai-rulez-generated.json` before editing any file under `skills/`, `commands/`, `.claude-plugin/`, or `.codex-plugin/`.
<!-- truth: end -->

## Canonical commands

```bash
# setup: (none - no install step needed)
# regenerate host packages: make generate
# focused tests: make test
# lint: make lint
# validation: make validate
# aggregate verification: make check
# full verification with smoke: make check-all
# release preparation: make release
```

Use non-interactive modes in automation. Before claiming a result, run the exact command freshly, read its complete output and exit status, and report limitations.

## The loop

```bash
# 1. edit a source under .ai-rulez/
# 2. regenerate the host packages
make generate
# 3. run exactly what CI runs
make check
# 4. commit sources AND generated output together
```

Generated files are committed on purpose, so users can install the plugin without having `ai-rulez`. A commit that changes a source without its regenerated output fails `ai-rulez verify --plugin`.

## Direct-read continuity

1. Resolve `.agents/setup-state.json:root_directory`, defaulting to `.agents/`.
2. Read unresolved transaction journals under `<configured-root>/transactions/` before normal work.
3. Read active/completed spec frontmatter and Continuity Snapshot, then all task frontmatter.
4. Verify plan identity, state revision bounds, current claim, dependencies, and checklist agreement.
5. Select an explicit task, the sole in-progress task, or the first ready task ordered by priority, creation time, and id.
6. Read the complete worksheet, direct dependencies, newest discoveries, and only the relevant project-shaped knowledge chapters.

Hooks and prior conversation are routing hints, not authority. State operations use ordinary file tools and the packaged Flow state contract; there is no Flow CLI or consumer Python runtime.

## Task and state operations

A task is ready when `state: open`, all `depends_on` tasks are `closed`, its worksheet is complete, and its plan identity matches the spec.

| Operation | Purpose |
| --- | --- |
| `claim` | Move one ready task to `in_progress` and set the spec current task. |
| `discover` | Append investigation evidence without changing the worksheet. |
| `block` / `unblock` | Record or resolve an exact blocker and next step. |
| `release` | Return an in-progress task to open when the claimant stops. |
| `checkpoint` | Bind fresh task, phase, or plan evidence. |
| `close` | Close the sole claimed task with commit-bound evidence. |
| `revise` | Change approved plan-bearing content and increment plan identity. |
| `reconcile` | Update derived spec checklist/snapshot from task-file truth. |
| `complete` / `archive` | Finish verified work, synthesize knowledge, log, then contract the spec directory. |
| `recover` | Resume or roll back one recorded interrupted transaction. |

Never edit task/spec state or checklist markers independently. Apply task changes before spec changes in one journaled state transaction and reread the result.

## Verification strategies

| Strategy | Select for | Required evidence |
| --- | --- | --- |
| `behavior_tdd` | New observable behavior | Focused behavior fails because it is absent; minimal implementation makes it green. |
| `regression_tdd` | Defect correction | Focused reproduction demonstrates the defect; the narrow fix makes it green. |
| `characterization` | Behavior-preserving refactor/deletion | Green focused baseline before and unchanged behavior after. |
| `static_validation` | Manifest, config, generated surface, tooling | Native parser/lint/type/build; isolated representative violation proves a new/replacement gate fails with the expected diagnostic. |
| `documentation_validation` | Links, examples, docs structure | Docs-native baseline and final link/example/build/structure checks. |
| `integration_acceptance` | Composition of existing contracts | Green focused baseline; end-to-end scenario plus injected negative states proving refusal paths. |

## Quality gates

Before close or checkpoint, require:

- worksheet acceptance criteria satisfied with fresh evidence;
- selected verification strategy followed;
- `make check` green;
- no accidental changes outside task scope;
- no unrelated paths staged and `git diff --check` clean;
- discoveries and verification limitations recorded.
