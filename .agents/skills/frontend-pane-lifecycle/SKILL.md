---
name: frontend-pane-lifecycle
description: Build and debug pane lifecycle behavior in the React frontend. Use when adding pane actions, layout behavior, rendering updates, or pane-level interactions.
license: Apache-2.0
compatibility: Requires React/webpack frontend context and Cypress UI test execution.
---

# Skill: Frontend Pane Lifecycle

## When to Use

Use this skill when changing pane rendering, pane actions, or lifecycle events.

## Core Workflow

1. Trace pane flow in `js/main.js` from incoming command to rendered pane.
2. Update pane components in `js/panes/` with existing memo/ref patterns.
3. Keep layout and focus behavior compatible with current grid logic.
4. Ensure topbar and modal interactions remain coherent with pane state.
5. Verify close/save/reset behavior and content refresh semantics.

## Guardrails

- Preserve `React.memo` and render-coalescing assumptions.
- Do not break pane IDs, titles, or layout item contracts.
- Keep compatibility with existing pane types and settings registration.

## Documentation

- [Skill reference](references/REFERENCE.md)
- `js/main.js`
- `js/panes/`
- `js/settings.js`
- `js/topbar/`
- `AGENTS.md`
- `CONTRIBUTING.md`

## Assets

- See `assets/README.md` and store templates/resources in `assets/`.

## Tests

- Follow the default flow in `references/TESTS.md`.

