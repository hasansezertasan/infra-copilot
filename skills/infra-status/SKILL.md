---
name: infra-status
description: "Read-only health check: runs every step's check across the whole manifest and reports what is green, which step is the first red, and which skill fixes it. Changes nothing. Use when the question is where infra stands rather than a request to change it."
allowed-tools: Read, Bash, Glob, Grep, Task
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:fca82bd7ad6ee79306f280de29852bed13dcc9e5f9a2258668b4bb2b17e281c7
Source-Hash: blake3:42c7574fde1dc55e8f96bd54590bf4f29122805f262a3a990b60d7f7f4763ae5
Schema-Version: v1
-->

# infra-status

## Workflow

Route the health check through the shared status runbook:
[`../infra/references/status.md`](../infra/references/status.md). It loads
the Config block from the root `README.md`, and stops with an "unsupported" message when a
legacy `.infra-copilot/` directory or `.claude/infra-copilot.local.md`
file is still present.

That reference owns the scan, safety classification, reporting rules, and validation.

## Guardrails

Keep this entry point read-only. Follow the shared runbook's actor and mutation rules.

## Validation

Use the report contract in the shared runbook; do not define another result model here.

## Example

Use this skill when the user asks for current infrastructure status without changes.
