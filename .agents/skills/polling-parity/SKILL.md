---
name: polling-parity
description: Keep feature behavior identical across WebSocket and polling transport modes. Use when adding socket commands, event flows, or transport-sensitive UI updates.
license: Apache-2.0
compatibility: Requires access to Visdom server runtime, Cypress tests, and both socket/polling execution paths.
---

# Skill: Polling and WebSocket Parity

## When to Use

Use this skill for any real-time feature that touches transport behavior.

## Core Workflow

1. Implement feature changes in the primary socket path.
2. Mirror equivalent behavior in polling wrappers/fallback logic.
3. Confirm command names and payload shapes are transport-neutral.
4. Validate environment switch, pane update, and callback routing in both modes.
5. Ensure no mode-specific regressions in reconnect/reload behavior.

## Guardrails

- Do not ship socket-only features.
- Keep command contracts stable across both modes.
- Avoid mode-specific payload forks unless explicitly versioned.

## Documentation

- [Skill reference](references/REFERENCE.md)
- `py/visdom/server/handlers/socket_handlers.py`
- `js/api/ApiProvider.js`
- `js/api/Legacy.js`
- `AGENTS.md`
- `CONTRIBUTING.md`

## Assets

- See `assets/README.md` and store templates/resources in `assets/`.

## Tests

- Follow the default flow in `references/TESTS.md`.

