---
name: prune
description: "Remove spent import blocks from Terraform files after an import PR has merged and been applied. Fully automated — finds all import {} blocks, removes them, verifies terraform plan shows no changes, then commits and opens a PR. Run after an import PR merges."
---

# infra-copilot: prune

Remove one-shot `import {}` blocks from Terraform files after they've served their purpose.
Import blocks are only needed for the first apply — once the resource is in state, the block
is dead weight.

## When to use

After an import PR merges and applies successfully. The resources are now under management;
the import blocks can be removed.

## Workflow

1. **Find all import blocks** across `terraform/` directories:
   ```sh
   grep -rn "^import {" terraform/
   ```

2. **Remove each block** (the `import { ... }` stanza, typically 4 lines).

3. **Verify with terraform plan** — must show "No changes" for each affected leaf.
   If the plan shows changes, something went wrong with the original import.

4. **Commit and PR** with conventional title `chore(<provider>): remove import blocks`.

## Validation

```
No changes. Your infrastructure matches the configuration.
```

If any leaf shows drift, stop and investigate — the import may not have applied correctly.

## Automation

This skill is fully automated. No human steps, no credentials needed beyond what's already
configured for `terraform plan`. Safe to run as a post-merge hook.
