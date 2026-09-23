# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations,
explicitly targeting `hasansezertasan/infra-copilot` so a contributor fork cannot become the
tracker by accident.

## Conventions

- **Create an issue**. Use a heredoc for multi-line bodies:

  ```sh
  gh issue create --repo hasansezertasan/infra-copilot --title "..." --body "..."
  ```

- **Read an issue**:

  ```sh
  gh issue view <number> --repo hasansezertasan/infra-copilot --json title,body,labels,comments
  ```

  Add `--jq` when filtering comments.

- **List issues**, with appropriate `--label` and `--state` filters:

  ```sh
  gh issue list --repo hasansezertasan/infra-copilot --state open --limit 1000 \
    --json number,title,body,labels \
    --jq '[.[] | {number, title, body, labels: [.labels[].name]}]'
  ```

  Do not request `comments` in `gh issue list`: GitHub CLI truncates nested comments to the
  oldest 100 without pagination. For candidate issues requiring comment inspection, read
  complete comment histories individually via
  `gh issue view <number> --repo hasansezertasan/infra-copilot --json comments`.

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
    --json number,title,body,labels,author
  ```

  For each candidate, retrieve its association with
  `gh api repos/hasansezertasan/infra-copilot/pulls/<number> --jq .author_association`.
  Keep only `CONTRIBUTOR`, `FIRST_TIMER`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop
  `OWNER`/`MEMBER`/`COLLABORATOR`). `gh pr list` does not expose `authorAssociation`.
  Inspect complete comment histories individually via
  `gh pr view <number> --repo hasansezertasan/infra-copilot --comments`.

- **Comment / label / close**: `gh pr comment <number> --repo hasansezertasan/infra-copilot --body "..."`,
  `gh pr edit <number> --repo hasansezertasan/infra-copilot --add-label "..."`/
  `--remove-label "..."`, `gh pr close <number> --repo hasansezertasan/infra-copilot`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either:
resolve with `gh pr view 42 --repo hasansezertasan/infra-copilot` and fall back to
`gh issue view 42 --repo hasansezertasan/infra-copilot`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

```sh
gh issue view <number> --repo hasansezertasan/infra-copilot --json title,body,labels,comments
```

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets. The
`wayfinder:map`, `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, and
`wayfinder:task` labels exist on the repo; `gh issue create --label` fails on a label that
does not.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far /
  Fog body. Create it non-interactively with an explicit title and body:

  ```sh
  gh issue create --repo hasansezertasan/infra-copilot --label wayfinder:map \
    --title "<map title>" --body "<Notes / Decisions-so-far / Fog>"
  ```

- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the
  sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in
  the map body and put `Part of #<map>` at the top of the child body. Labels:
  `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket
  is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible
  representation. Add an edge with:

  ```sh
  gh api --method POST repos/hasansezertasan/infra-copilot/issues/<child>/dependencies/blocked_by \
    -F issue_id=<blocker-db-id>
  ```

  `<blocker-db-id>` is the blocker's numeric **database id**, not its `#number` and not its
  `node_id`. Read it with:

  ```sh
  gh api repos/hasansezertasan/infra-copilot/issues/<n> --jq .id
  ```

  Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the
  top of the child body. A ticket is unblocked when every blocker is closed.

- **Frontier query**: retrieve the map's `subIssues` first (or parse its task list where
  sub-issues are unavailable), preserving map order, then inspect only those children:

  ```sh
  gh issue view <child> --repo hasansezertasan/infra-copilot --json number,state,assignees,blockedBy
  ```

  `subIssues` and `blockedBy` are connection objects: read their `nodes`, compare the node
  count against `totalCount`, and paginate with GraphQL or fail closed if the connection
  cannot be retrieved in full. Drop a child that is closed, that has a `blockedBy` node
  whose `state` is `OPEN` (or an open issue named in a fallback `Blocked by:` line), or
  that has any assignee: the assignee _is_ the claim. First remaining child in map order
  wins. Do not use an unscoped `gh issue list`: it can include unrelated issues and
  defaults to 30 results.

- **Claim**: assign the ticket before any other work, then reread it:

  ```sh
  gh issue edit <n> --repo hasansezertasan/infra-copilot --add-assignee @me
  gh issue view <n> --repo hasansezertasan/infra-copilot --json state,assignees,blockedBy
  ```

  Assignment is not atomic, so the reread is the whole check. If a second assignee appears,
  or the ticket is now closed or blocked, remove only your own assignment and stop. A
  ticket already assigned to someone else is claimed, however old the claim looks: a human
  unassigns an abandoned ticket to return it to the frontier, and agents never reclaim one.

- **Resolve**: comment the answer, close the ticket, then append its context pointer
  (gist plus link) to the map's **Decisions so far**:

  ```sh
  gh issue comment <n> --repo hasansezertasan/infra-copilot --body "<answer>"
  gh issue close <n> --repo hasansezertasan/infra-copilot
  ```

  The pointer is a body edit rather than a comment, because `/wayfinder` loads the map body
  alone as its low-resolution view. Reread the body immediately before writing it, and redo
  the edit if it changed underneath you.
