# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations,
explicitly targeting `hasansezertasan/infra-copilot` so a contributor fork cannot become the
tracker by accident.

## Conventions

- **Create an issue**. Use a heredoc for multi-line bodies:

  ```sh
  gh issue create --repo hasansezertasan/infra-copilot --title "..." --body "..."
  ```

- **Read an issue**: `gh issue view <number> --repo hasansezertasan/infra-copilot --json title,body,labels,comments`,
  adding `--jq` when filtering comments.
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

Run `gh issue view <number> --repo hasansezertasan/infra-copilot \
--json title,body,labels,comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

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
  gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by \
    -F issue_id=<blocker-db-id>
  ```

  where `<blocker-db-id>` is the blocker's numeric **database id**
  (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`).
  GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only, the live
  gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line
  at the top of the child body. A ticket is unblocked when every blocker is closed.

- **Frontier query**: retrieve the map's `subIssues` first (or parse its task list where
  sub-issues are unavailable), preserving map order. Both `subIssues` and `blockedBy` are
  connection objects: use their `nodes`, compare the node count with `totalCount`, and paginate
  with GraphQL or fail closed if the complete connection cannot be retrieved. Inspect only those
  open child numbers with `gh issue view <child> --repo hasansezertasan/infra-copilot \
  --json number,state,body,assignees,blockedBy`; drop a closed child; any `blockedBy` item whose
  state is `OPEN`; or an open issue referenced by its fallback `Blocked by:` body line. An
  unassigned child is eligible. A child assigned to another user is not eligible and requires
  explicit human coordination. A child assigned solely to the current GitHub user is eligible only
  when an explicit stale-claim check permits same-user resume; see Claim. First remaining child in
  map order wins. Do not use an unscoped `gh issue list`: it can include unrelated issues and
  defaults to 30 results.
- **Claim**. First read `assignees` and proceed only when it is empty. Then make the session's
  first write and post the initial session marker:

  ```sh
  gh issue edit <n> --repo hasansezertasan/infra-copilot --add-assignee @me
  gh issue comment <n> --repo hasansezertasan/infra-copilot \
    --body "Wayfinder claim: <session-id> at <ISO-8601>"
  ```

  Immediately reread `assignees`: if any other assignee appears after the write, remove only
  the session's assignment and stop; do not infer that the other assignee follows this protocol.

  To arbitrate simultaneous claims from the same GitHub user, wait 5 seconds for convergence and
  reread comments. If another claim comment exists with an earlier `createdAt` (broken by
  lexicographically lower `session-id`), this session has lost: stop without removing the shared
  assignment. Only the winning session proceeds.

  While working, refresh the claim by appending a new
  `Wayfinder heartbeat: <session-id> at <ISO-8601>` comment. For work lasting longer than 60
  minutes, implementations must post heartbeats at a cadence strictly shorter than the lease
  interval (at least every 30 minutes). Never edit prior claim, heartbeat, or takeover comments.

  **Stale-claim check and same-user takeover**:
  - The repository lease interval is **60 minutes**.
  - Staleness checks MUST compare the GitHub comment `createdAt` timestamp (not the caller
    timestamp in the body) against the lease interval.
  - Only comments authored by the assigned GitHub user (`author.login == assigned_user`) count
    as valid claims, heartbeats, or takeovers.
  - A session may resume a sole assignment to its own GitHub user only if the assigned user's
    latest claim, heartbeat, or takeover comment has a `createdAt` older than 60 minutes.
    If the issue has no valid claim, heartbeat, or takeover comment (e.g. an earlier session
    crashed before posting its claim marker), evaluate staleness against the issue's `updatedAt`
    timestamp; if `updatedAt` is older than 60 minutes, the orphaned assignment is stale and
    resumable. Assignments to any other user remain ineligible and require explicit human
    coordination.
  - **Exclusive takeover**: When resuming, post an append-only takeover comment:
    `Wayfinder takeover: <new-session-id> at <ISO-8601>`.
    Wait 5 seconds for convergence and reread all comments posted after the expired lease marker.
    Arbitrate only takeover markers belonging to this current acquisition window. If a newer
    claim, heartbeat, or valid takeover appears, or if another takeover comment exists with an
    earlier `createdAt` (broken by lexicographically lower `session-id`), this session has lost:
    stop without removing the shared assignment. Only the winning session proceeds. Without
    proof that the prior lease is stale, leave the ticket for explicit human coordination.

- **Resolve**. Comment on the child, then add its context pointer (gist + link) as an append-only
  comment on the map before closing the child. The map's Decisions-so-far is read together with
  these `Context pointer:` comments. This avoids concurrent full-body edits that can overwrite a
  pointer. Verify the new map comment exists before closing:

  ```sh
  gh issue comment <n> --repo hasansezertasan/infra-copilot --body "<answer>"
  gh issue comment <map> --repo hasansezertasan/infra-copilot \
    --body "Context pointer: <gist + link>"
  gh issue close <n> --repo hasansezertasan/infra-copilot
  ```
