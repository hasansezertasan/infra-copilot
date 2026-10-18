# README sections replace the `.infra-copilot/` state directory

Status: proposed, not yet implemented; the Skills still read the old state directory until
the tickets under #130 land.

An Infra repo keeps its public identifiers and human attestations in a Config block, and its
locked choices in a Decisions table, as fixed sections of the root `README.md`. The
`.infra-copilot/` directory and the legacy `.claude/infra-copilot.local.md` are no longer
supported: the Skills detect them, report that they are unsupported, and stop. The checks still
need a machine-readable locked-decision table, so Keep the Why is an optional home for long-form
rationale only.

## Considered Options

- Keep `.infra-copilot/config.md` and `decisions.md`: rejected because the Template would then
  have to render files named after the product, which makes any rename a breaking contract
  change across two repos.
- Keep the Why as the only decision record: rejected because checks parse locked rows for the
  apply gate, provider authentication and `allow-destroy`, and a prose record cannot be parsed.
- Automated migration from the legacy directory: rejected because the audience is small and
  migration code is more to maintain than a documentation note.
