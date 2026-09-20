# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations,
explicitly targeting `hasansezertasan/infra-copilot` so a contributor fork cannot become the
tracker by accident.

## Conventions

- **Create an issue**. Use a heredoc for multi-line bodies:

  ```sh
  gh issue create --repo hasansezertasan/infra-copilot --title "..." --body "..."
  ```

- **Read an issue**: `gh issue view <number> --repo hasansezertasan/infra-copilot --json labels,comments`,
  adding `--jq` when filtering comments.
- **List issues**, with appropriate `--label` and `--state` filters:

  ```sh
  gh issue list --repo hasansezertasan/infra-copilot --state open --limit 1000 \
    --json number,title,body,labels,comments \
    --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'
  ```

- **Comment on an issue**: `gh issue comment <number> --repo hasansezertasan/infra-copilot --body "..."`
- **Apply / remove labels**:
  `gh issue edit <number> --repo hasansezertasan/infra-copilot --add-label "..."` /
  `gh issue edit <number> --repo hasansezertasan/infra-copilot --remove-label "..."`
- **Close**: `gh issue close <number> --repo hasansezertasan/infra-copilot --comment "..."`

The explicit `--repo` is intentional: do not infer the tracker from the current clone's remotes.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as
feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr`
equivalents:

- **Read a PR**: `gh pr view <number> --repo hasansezertasan/infra-copilot --comments` and
  `gh pr diff <number> --repo hasansezertasan/infra-copilot` for the diff.
- **List external PRs for triage**:

  ```sh
  gh pr list --repo hasansezertasan/infra-copilot --state open --limit 1000 \
    --json number,title,body,labels,author,comments
  ```

  For each candidate, retrieve its association with
  `gh api repos/hasansezertasan/infra-copilot/pulls/<number> --jq .author_association`.
  Keep only `CONTRIBUTOR`, `FIRST_TIMER`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop
  `OWNER`/`MEMBER`/`COLLABORATOR`). `gh pr list` does not expose `authorAssociation`.

- **Comment / label / close**: `gh pr comment <number> --repo hasansezertasan/infra-copilot --body "..."`,
  `gh pr edit <number> --repo hasansezertasan/infra-copilot --add-label "..."`/
  `--remove-label "..."`, `gh pr close <number> --repo hasansezertasan/infra-copilot`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either:
resolve with `gh pr view 42 --repo hasansezertasan/infra-copilot` and fall back to
`gh issue view 42 --repo hasansezertasan/infra-copilot`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --repo hasansezertasan/infra-copilot \
--json title,body,labels,comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far /
  Fog body. `gh issue create --repo hasansezertasan/infra-copilot --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the
  sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in
  the map body and put `Part of #<map>` at the top of the child body. Labels:
  `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket
  is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible
  representation. Add an edge with:

  ```sh
  gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by \
    -F issue_id=<blocker-db-id>
  ```

  where `<blocker-db-id>` is the blocker's numeric **database id**
  (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`).
  GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only, the live
  gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line
  at the top of the child body. A ticket is unblocked when every blocker is closed.

- **Frontier query**: retrieve the map's `subIssues` first (or parse its task list where
  sub-issues are unavailable), preserving map order. Inspect only those open child numbers
  with `gh issue view <child> --repo hasansezertasan/infra-copilot \
  --json number,state,body,assignees,blockedBy`; drop a closed child; a child with an
  assignee; any `blockedBy` item whose state is `OPEN`; or an open issue referenced by its
  fallback `Blocked by:` body line. First remaining child in map order wins. Do not use an
  unscoped `gh issue list`: it can include unrelated issues and defaults to 30 results.
- **Claim**. The session's first write, followed immediately by a reread of `assignees`:

  ```sh
  gh issue edit <n> --repo hasansezertasan/infra-copilot --add-assignee @me
  ```

  If more than one assignee is present, this is a concurrent claim. The lexicographically
  lowest GitHub login wins; every other claimant must not begin work and must remove only
  their own assignment. The winner rereads until they are the sole assignee before work begins.

- **Resolve**. Comment, close, then append a context pointer (gist + link) to the map's
  Decisions-so-far:

  ```sh
  gh issue comment <n> --repo hasansezertasan/infra-copilot --body "<answer>"
  gh issue close <n> --repo hasansezertasan/infra-copilot
  ```
