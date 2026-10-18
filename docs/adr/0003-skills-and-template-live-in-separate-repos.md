# The Skills and the Template live in separate repos that promote each other

Status: accepted. `infra-setup` renders the Template and checks its recorded version (#134);
`infra-import` adopting the Template follows in #135.

`infra-skills` ships the Skills and `copier-infra` ships the Template, as `scoop-bucket-skills`
and `homebrew-tap-skills` do with their templates. The Skills render the Template and never
hand-write files it owns. They accept a minimum Template version judged from the `_commit`
field of `.copier-answers.yml`, so the Template can be released first and the Skills depend on
a tag that exists. The minimum is a release tag in `vX.Y.Z` form, compared as semantic
versions. A tag at or above it passes and an older tag proposes the Template's update. A bare
commit hash or a between-tags value such as `v0.1.0-3-gabc1234` cannot be compared, so the
Skills treat it as indeterminate and hand off to the human instead of guessing.

## Considered Options

- Ship the skills inside the Template: rejected because every consumer would carry skill files
  that must update on a different cadence than the repo skeleton.
- Keep the Template inside this repo: rejected because `copier update` consumers would track the
  plugin's release cadence instead of the Template's own.
