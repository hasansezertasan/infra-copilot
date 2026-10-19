# infra-skills

Agent skills that bootstrap and maintain an infrastructure repository, paired with a Copier template that renders that repository's starting shape. The two promote each other.

Vocabulary for the pairing tracked in #130. The plugin is renamed and the Skills read the
Config block and Decisions table from the README, and `infra-setup` renders the Template and
enforces the Template contract.

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

**Handoff**:
The stop-and-ask block the Skills emit when a step needs work only a human can do, ending in a statement of what the Skills will check once the human says done.
_Avoid_: Prompt, instruction, manual step
