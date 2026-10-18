# The Skills and the Template live in separate repos that promote each other

`infra-skills` ships the Skills and `copier-infra` ships the Template, as `scoop-bucket-skills`
and `homebrew-tap-skills` do with their templates. The Skills render the Template and never
hand-write files it owns. They accept a minimum Template version judged from the version
recorded in `.copier-answers.yml`, so the Template can be released first and the Skills depend
on a tag that exists.

## Considered Options

- Ship the skills inside the Template: rejected because every consumer would carry skill files
  that must update on a different cadence than the repo skeleton.
- Keep the Template inside this repo: rejected because `copier update` consumers would track the
  plugin's release cadence instead of the Template's own.
