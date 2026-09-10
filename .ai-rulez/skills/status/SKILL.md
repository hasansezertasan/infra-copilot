---
name: status
description: "Read-only health check: runs every step's check across the whole manifest and reports what is green, which step is the first red, and which skill fixes it. Changes nothing. Use when the question is where infra stands rather than a request to change it."
---

# infra-copilot: status

## Workflow

Route the health check through the shared status runbook:
[`../infra-copilot/references/status.md`](../infra-copilot/references/status.md). It loads
`.infra-copilot/config.md`, with `.claude/infra-copilot.local.md` as the documented legacy
fallback.

That reference owns the scan, safety classification, reporting rules, and validation.

## Guardrails

Keep this entry point read-only. Follow the shared runbook's actor and mutation rules.

## Validation

Use the report contract in the shared runbook; do not define another result model here.

## Example

Use this skill when the user asks for current infrastructure status without changes.
