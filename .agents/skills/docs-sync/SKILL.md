---
name: docs-sync
description: Keep API and behavior documentation aligned across README, contribution docs, and AI instructions
---

# Skill: Documentation Synchronization

## When to Use

Use this skill when behavior/API changes must be reflected in project docs.

## Core Workflow

1. Identify impacted behavior surface (user API, server internals, contributor workflow, AI workflow).
2. Update `README.md` for high-level usage and navigation-impacting changes.
3. Update `CONTRIBUTING.md` for developer workflow, testing, and submission changes.
4. If AI-agent workflow changes, update `AGENTS.md` and keep assistant-specific instruction files pointing to it.
5. Ensure any examples in docs match current callable APIs and option names.

## Guardrails

- Avoid contradictory examples between docs.
- Keep terminology consistent (`env`, `win`, `pane`, `update`).
- When API signatures change, ensure examples and type stubs are updated together.

## Documentation

- [Skill reference](references/REFERENCE.md)
- `README.md`
- `CONTRIBUTING.md`
- `AGENTS.md`

## Assets

- See `assets/README.md` and store templates/resources in `assets/`.

## Tests

- Follow the default flow in `references/TESTS.md`.
