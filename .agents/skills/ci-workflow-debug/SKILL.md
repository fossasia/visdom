---
name: ci-workflow-debug
description: Diagnose and fix GitHub Actions workflow failures. Use when CI jobs fail for lint, tests, JS build updates, or release automation.
license: Apache-2.0
compatibility: Requires access to .github/workflows and local equivalents of CI commands.
---

# Skill: CI Workflow Debugging

## When to Use

Use this skill when pull requests fail checks or automation jobs.

## Core Workflow

1. Identify failing job scope (lint, tests, build artifacts, release pipeline).
2. Reproduce failure locally with matching commands.
3. Fix root cause while preserving existing workflow intent.
4. Confirm related jobs are not impacted by the fix.
5. Keep automation assumptions aligned with repository policies.

## Guardrails

- Do not patch around failures by weakening tests/lints.
- Keep release and JS auto-build workflows intact.
- Avoid introducing branch- or actor-specific CI logic hacks.

## Documentation

- [Skill reference](references/REFERENCE.md)
- `.github/workflows/`
- `package.json`
- `test-requirements.txt`
- `AGENTS.md`
- `CONTRIBUTING.md`

## Assets

- See `assets/README.md` and store templates/resources in `assets/`.

## Tests

- Follow the default flow in `references/TESTS.md`.

