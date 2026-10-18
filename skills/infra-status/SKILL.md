---
name: infra-status
description: "Read-only health check: runs every step's check across the whole manifest and reports what is green, which step is the first red, and which skill fixes it. Changes nothing. Use when the question is where infra stands rather than a request to change it."
allowed-tools: Read, Bash, Glob, Grep, Task
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:3feccbbbf1a035d4f900224a21089b0313bf4161a4f659b55f884140bccb8d3b
Source-Hash: blake3:bc3035ae93f0d480805e2aa47fc30257a53ec0a06c0ebbeb36e6fe1679fa5ebb
Schema-Version: v1
-->

# infra-status

## Workflow

Route the health check through the shared status runbook:
[`../infra/references/status.md`](../infra/references/status.md). It loads
`.infra-copilot/config.md`, with `.claude/infra-copilot.local.md` as the documented legacy
fallback.

That reference owns the scan, safety classification, reporting rules, and validation.

## Guardrails

Keep this entry point read-only. Follow the shared runbook's actor and mutation rules.

## Validation

Use the report contract in the shared runbook; do not define another result model here.

## Example

Use this skill when the user asks for current infrastructure status without changes.
