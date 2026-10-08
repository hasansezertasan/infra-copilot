<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:45addcf9253c687839a6528c7fc41272ed8504d60f7178dc34f48a89e67b2d21
Source-Hash: blake3:cbe7b5636d9cfe98f2765d0a6bcd5a8b31703891d01bd8c43151898e6e91f278
Schema-Version: v1
-->

# Prune spent blocks

Only remove leaf-local `import {}` and `moved {}` blocks after their apply has landed.
Never remove configuration blocks, module upgrade instructions, or `removed {}` blocks.
Open a separate pull request per leaf, after the import PR merged and applied.

## Workflow

1. Discover top-level instruction blocks in committed `.tf` and `.tf.json` leaf files.
   Exclude `terraform/modules/`, comments, strings and heredocs. The
   `prune-spent-imports` check discriminates these cases; a textual match it does not
   report is not a candidate.
2. Follow [prune-blocks](../operations.md#prune-blocks) for the selected execution
   procedure. State membership alone is insufficient, particularly for aggregate
   addresses, index changes and chained moves. Let Terraform decide whether a block is spent.
3. Remove only proven spent blocks. Obtain a plan for the committed deletion with
   [get-plan](../operations.md#get-plan). Require `No changes.` with no imports, moves,
   creates, changes or destroys. Restore the blocks and stop on any other result.
4. Open the leaf's PR with the no-op plan evidence. A green manifest scan means no
   committed instruction blocks remain across all leaves; it does not replace the plan.

## Validation

The selected execution procedure proves the blocks have applied and the deletion's plan
is a no-op. An unreadable state or plan is unknown, never permission to delete.
