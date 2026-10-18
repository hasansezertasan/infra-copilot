# infra-skills

Agent skills that bootstrap and maintain an infrastructure repository, paired with a Copier template that renders that repository's starting shape. The two promote each other.

Target vocabulary for the rename tracked in #130. Until it lands, the plugin is still named
infra-copilot and the Template contract is not yet enforced.

## Language

**Infra repo**:
A repository, rendered from the template and kept healthy by the skills, that holds an organisation's infrastructure code.
_Avoid_: Consumer repo, target repo

**Template**:
The Copier template (`copier-infra`) that renders an Infra repo's initial files, including its Config block and Decisions table.
_Avoid_: Scaffold, boilerplate

**Skills**:
This plugin's agent skills, which operate on an Infra repo and never hand-write files the Template owns.
_Avoid_: Copilot, assistant

**Config block**:
The fixed README section holding an Infra repo's public identifiers and human attestations, which the Skills read.
_Avoid_: config.md, settings file

**Decisions table**:
The fixed README section listing an Infra repo's locked choices, which the Skills check.
_Avoid_: decisions.md, decision log

**Template contract**:
The minimum Template version the Skills accept, judged from the version recorded when the Infra repo was rendered.
_Avoid_: Compatibility matrix
