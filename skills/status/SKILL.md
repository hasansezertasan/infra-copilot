---
name: status
description: "Read-only health check: runs every step's check across the whole manifest and reports what is green, which step is the first red, and which skill fixes it. Changes nothing. Use when the question is where infra stands rather than a request to change it."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:dadc4bf5a553cfc7675e8428f0091d22674633843ed4edcfb10351f974c39faa
Source-Hash: blake3:1ecaa10bad1b907246dfd8be25b4c83c4f29a427df437b6c5fb2a8840dbb3ef8
Schema-Version: v1
-->

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
